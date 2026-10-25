"""
app.integrations.sap.client
==============================
Async HTTP client for the SAP Business One Service Layer (SAP's
OData-style REST API). Handles session-based authentication (Service
Layer uses a login-once, cookie-based session — not a bearer token per
request) and generic CRUD against any resource, so
`app.services.sap_sync_service` never touches `httpx` directly.

SESSION HANDLING
-------------------
`POST /Login` with `{CompanyDB, UserName, Password}` returns a
`B1SESSION` cookie (and, in a load-balanced deployment, a `ROUTEID`
cookie that must be replayed on every subsequent request so all calls
in a session land on the same Service Layer node). `httpx.AsyncClient`
manages cookies automatically across requests made through the same
client instance, which is why this class owns exactly one
`AsyncClient` for its lifetime rather than creating one per call.

Service Layer sessions expire (default ~30 minutes, configurable
server-side). `request()` catches a 401 on any call, attempts exactly
one re-login, and retries the call once — a second 401 after that is
treated as a real auth problem (`SAPSessionExpiredError`), not a
transient timeout, so callers don't get stuck in a silent retry loop.

*** THIS CLIENT HAS NOT BEEN EXERCISED AGAINST A REAL SAP B1 SERVICE
LAYER INSTANCE *** — there was no live SAP sandbox available while
building this. The request/response shapes and login flow follow SAP's
publicly documented Service Layer behavior, and the unit tests in
tests/unit/test_sap_client.py verify the client's logic (session
handling, retry-on-401, error parsing) against a mocked transport — but
that is not the same as proving it works against a real Service Layer
deployment. Treat this as implementation-complete-but-unverified, and
run it against a real SAP B1 sandbox/demo company before any production
use. This is the same honesty standard applied to the object-type codes
in app.core.sap_reference — verify before relying on it.

USAGE
-----
    async with SAPServiceLayerClient() as client:
        bp = await client.get("BusinessPartners", "V0001234")
        await client.post("BusinessPartners", {"CardCode": "V0001234", ...})
        await client.patch("BusinessPartners", "V0001234", {"EmailAddress": "..."})
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.sap.exceptions import (
    SAPAuthenticationError,
    SAPRequestError,
    SAPSessionExpiredError,
    SAPPotentialDuplicateError,
    SAPTransportError,
)

logger = get_logger(__name__)


class SAPServiceLayerClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        company_db: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_ssl: bool | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        sap_settings = settings.sap
        self._base_url = (base_url or str(sap_settings.service_layer_url or "")).rstrip("/")
        self._company_db = company_db or sap_settings.company_db
        self._username = username or sap_settings.username
        self._password = password or (
            sap_settings.password.get_secret_value() if sap_settings.password else None
        )
        verify = sap_settings.verify_ssl if verify_ssl is None else verify_ssl

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            verify=verify,
            timeout=request_timeout_seconds,
            transport=transport,  # None -> httpx's real transport; a test transport otherwise
        )
        self._logged_in = False

    async def __aenter__(self) -> "SAPServiceLayerClient":
        await self.login()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._logged_in:
            try:
                await self.logout()
            except Exception:  # noqa: BLE001 — best-effort cleanup, never raise on close
                logger.warning("sap_logout_failed_during_close")
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    async def login(self) -> None:
        if not (self._base_url and self._company_db and self._username and self._password):
            raise SAPAuthenticationError(
                "SAP Service Layer is not fully configured (base URL, "
                "CompanyDB, username, and password are all required).",
            )
        response = await self._client.post(
            "/Login",
            json={
                "CompanyDB": self._company_db,
                "UserName": self._username,
                "Password": self._password,
            },
        )
        if response.status_code != 200:
            raise SAPAuthenticationError(
                f"SAP Service Layer login failed with status {response.status_code}.",
                details={"status_code": response.status_code, "body": _safe_body(response)},
            )
        if not self._client.cookies.get("B1SESSION"):
            raise SAPAuthenticationError(
                "SAP Service Layer login returned success but no B1SESSION cookie was established.",
                details={"status_code": response.status_code},
            )
        self._logged_in = True
        logger.info("sap_login_succeeded", company_db=self._company_db)

    async def logout(self) -> None:
        await self._client.post("/Logout")
        self._logged_in = False
        logger.info("sap_logout_succeeded")

    # ------------------------------------------------------------------
    # Generic CRUD
    # ------------------------------------------------------------------
    async def get(
        self, resource: str, entry_id: str | int | None = None, *, params: dict | None = None
    ) -> dict[str, Any]:
        path = f"/{resource}" if entry_id is None else f"/{resource}('{entry_id}')"
        return await self._request("GET", path, resource=resource, params=params)

    async def post(self, resource: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/{resource}", resource=resource, json=payload)

    async def patch(
        self, resource: str, entry_id: str | int, payload: dict[str, Any]
    ) -> None:
        """SAP returns 204 No Content on a successful PATCH — nothing to
        parse, so this returns None rather than an empty dict."""
        await self._request(
            "PATCH", f"/{resource}('{entry_id}')", resource=resource, json=payload
        )

    async def delete(self, resource: str, entry_id: str | int) -> None:
        await self._request("DELETE", f"/{resource}('{entry_id}')", resource=resource)

    # ------------------------------------------------------------------
    # Internal request handling: auth, retry-on-401, error parsing
    # ------------------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        resource: str,
        json: dict | None = None,
        params: dict | None = None,
        _retried_after_relogin: bool = False,
    ) -> dict[str, Any]:
        if not self._logged_in:
            await self.login()

        try:
            response = await self._send_with_retry(method, path, json=json, params=params)
        except httpx.TransportError as exc:
            if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                raise SAPPotentialDuplicateError(
                    "SAP mutating request ended without a reliable response. Automatic "
                    "retry is blocked because the operation may already have committed; "
                    "reconcile the SAP record before another attempt.",
                    method=method,
                    resource=resource,
                ) from exc
            raise SAPTransportError(
                f"SAP Service Layer transport failed for {method} {path} after bounded retries."
            ) from exc

        # Never blindly replay a financial mutation after an authentication
        # failure: the first request may have reached SAP even if the response
        # was lost. Read-only calls are safe to replay after a session refresh.
        if response.status_code == 401 and not _retried_after_relogin:
            if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                raise SAPSessionExpiredError(
                    "SAP session expired during a mutating request. Automatic replay was "
                    "intentionally skipped because the original financial operation may "
                    "have reached SAP; reconcile the operation before retrying."
                )
            logger.info("sap_session_expired_reauthenticating")
            await self.login()
            return await self._request(
                method, path, resource=resource, json=json, params=params,
                _retried_after_relogin=True,
            )
        if response.status_code == 401:
            raise SAPSessionExpiredError(
                "SAP Service Layer session expired and re-authentication also failed."
            )

        if response.status_code >= 400:
            sap_code, sap_message = _parse_sap_error(response)
            raise SAPRequestError(
                f"SAP Service Layer request failed: {method} {path} -> {response.status_code}",
                status_code=response.status_code,
                resource=resource,
                sap_error_code=sap_code,
                sap_error_message=sap_message,
            )

        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    async def _send_with_retry(
        self, method: str, path: str, *, json: dict | None, params: dict | None
    ) -> httpx.Response:
        # Automatic transport retries are limited to operations whose replay
        # cannot create a duplicate financial transaction. Mutations require
        # an explicit idempotency/reconciliation strategy at the integration
        # boundary instead of a blind network retry.
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            return await self._client.request(method, path, json=json, params=params)

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=6),
            retry=retry_if_exception_type(httpx.TransportError),
            reraise=True,
        )
        async def _do_send() -> httpx.Response:
            return await self._client.request(method, path, json=json, params=params)

        return await _do_send()


def _parse_sap_error(response: httpx.Response) -> tuple[int | None, str | None]:
    try:
        body = response.json()
        error = body.get("error", {})
        code = error.get("code")
        message = error.get("message", {})
        message_value = message.get("value") if isinstance(message, dict) else str(message)
        return code, message_value
    except Exception:  # noqa: BLE001 — response wasn't JSON or didn't match the expected shape
        return None, None


def _safe_body(response: httpx.Response) -> str:
    try:
        return response.text[:500]
    except Exception:  # noqa: BLE001
        return "<unreadable response body>"
