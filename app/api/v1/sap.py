from __future__ import annotations
from datetime import datetime, timezone
from time import monotonic
import httpx
from fastapi import APIRouter, Depends, Request
from app.api.deps import ActorContext, require_permission
from app.core.config import settings
from app.core.constants import Permission
from app.core.logging import get_correlation_id, get_logger
from app.integrations.sap.client import SAPServiceLayerClient
from app.integrations.sap.exceptions import SAPAuthenticationError, SAPRequestError, SAPSessionExpiredError, SAPTransportError
from app.schemas.agent import RunSAPIntegrationAgentRequest
from app.schemas.sap_status import SAPStatusRead, SAPVerificationRead

router = APIRouter(prefix="/sap", tags=["sap"])
logger = get_logger(__name__)

@router.get("/status", response_model=SAPStatusRead)
async def sap_status(actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE))) -> SAPStatusRead:
    del actor
    sap = settings.sap
    url_configured = bool(sap.service_layer_url)
    company_configured = bool(sap.company_db and sap.company_db.strip())
    credentials_configured = bool(sap.username and sap.username.strip() and sap.password and sap.password.get_secret_value())
    return SAPStatusRead(
        enabled=sap.enabled,
        configured=url_configured and company_configured and credentials_configured,
        service_layer_url_configured=url_configured,
        company_db_configured=company_configured,
        credentials_configured=credentials_configured,
        verify_ssl=sap.verify_ssl,
        live_connection_verified=False,
        supported_entities=list(RunSAPIntegrationAgentRequest.model_json_schema()["properties"]["entity_type"]["enum"]),
    )

@router.post("/verify", response_model=SAPVerificationRead)
async def verify_sap_read_only(
    request: Request,
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> SAPVerificationRead:
    """Bounded, read-only Service Layer probe. Never writes SAP data."""
    del actor
    sap = settings.sap
    correlation_id = getattr(request.state, "correlation_id", None) or get_correlation_id()
    now = datetime.now(timezone.utc)
    common = {"checked_at": now, "probe_resource": "BusinessPartners", "correlation_id": correlation_id}
    if not sap.enabled:
        return SAPVerificationRead(state="disabled", message="SAP integration is disabled by server configuration.", error_category="disabled", **common)
    has_any = bool(sap.service_layer_url or sap.company_db or sap.username or (sap.password and sap.password.get_secret_value()))
    configured = bool(sap.service_layer_url and sap.company_db and sap.company_db.strip() and sap.username and sap.username.strip() and sap.password and sap.password.get_secret_value())
    if not has_any:
        return SAPVerificationRead(state="not_configured", message="SAP connection details are not configured.", error_category="not_configured", **common)
    if not configured:
        return SAPVerificationRead(state="configuration_invalid", message="SAP configuration is incomplete. Check server-side environment settings.", error_category="configuration_invalid", **common)
    if not sap.verify_ssl:
        return SAPVerificationRead(state="configuration_invalid", message="TLS certificate verification must be enabled before SAP connectivity checks.", error_category="tls_verification_disabled", **common)
    started = monotonic()
    client = SAPServiceLayerClient(base_url=str(sap.service_layer_url), company_db=sap.company_db,
        username=sap.username, password=sap.password.get_secret_value(), verify_ssl=True, request_timeout_seconds=10.0)
    try:
        await client.login()
        try:
            response = await client.get("BusinessPartners", params={"$top": 1, "$select": "CardCode,CardName,CardType"})
        except SAPRequestError as exc:
            logger.warning("sap_read_only_probe_rejected", correlation_id=correlation_id, status_code=exc.status_code,
                resource="BusinessPartners", duration_ms=round((monotonic()-started)*1000, 2))
            return SAPVerificationRead(state="authenticated_and_reachable",
                message="SAP authentication succeeded, but the read-only business-partner probe was rejected.",
                error_category="read_rejected", **common)
        values = response.get("value") if isinstance(response, dict) else None
        if not isinstance(values, list):
            logger.warning("sap_read_only_probe_malformed_response", correlation_id=correlation_id,
                response_type=type(response).__name__, duration_ms=round((monotonic()-started)*1000, 2))
            return SAPVerificationRead(state="read_only_verification_failed",
                message="SAP authenticated, but the read response did not match the expected Service Layer shape.",
                error_category="invalid_response_shape", **common)
        logger.info("sap_read_only_probe_passed", correlation_id=correlation_id, resource="BusinessPartners",
            records_returned=len(values), duration_ms=round((monotonic()-started)*1000, 2))
        return SAPVerificationRead(state="read_only_verification_passed",
            message="SAP authentication and read-only business-partner probe succeeded.", records_returned=len(values),
            verified_at=datetime.now(timezone.utc), **common)
    except (SAPAuthenticationError, SAPSessionExpiredError):
        logger.warning("sap_read_only_probe_authentication_failed", correlation_id=correlation_id,
            duration_ms=round((monotonic()-started)*1000, 2))
        return SAPVerificationRead(state="authentication_failed",
            message="SAP authentication failed. Check the server-side credentials and CompanyDB.",
            error_category="authentication_failed", **common)
    except (SAPTransportError, httpx.TransportError, TimeoutError):
        logger.warning("sap_read_only_probe_connection_failed", correlation_id=correlation_id,
            duration_ms=round((monotonic()-started)*1000, 2))
        return SAPVerificationRead(state="connection_unreachable",
            message="SAP Service Layer could not be reached within the configured timeout.",
            error_category="connection_unreachable", **common)
    except Exception as exc:  # noqa: BLE001 - sanitize unexpected downstream failures
        logger.error("sap_read_only_probe_failed", correlation_id=correlation_id, error_type=type(exc).__name__,
            duration_ms=round((monotonic()-started)*1000, 2))
        return SAPVerificationRead(state="read_only_verification_failed",
            message="SAP verification failed. Use the correlation ID for restricted server-side diagnostics.",
            error_category="unexpected_error", **common)
    finally:
        try:
            await client.close()
        except Exception as exc:  # noqa: BLE001 - cleanup must not hide result
            logger.warning("sap_read_only_probe_cleanup_failed", correlation_id=correlation_id, error_type=type(exc).__name__)
