"""
app.integrations.sap.exceptions
==================================
Exceptions specific to the SAP Service Layer client, layered on top of
`app.core.exceptions.ExternalServiceError` so they're caught correctly
by the existing global exception handler (returns HTTP 502 — a
downstream dependency failure — without any SAP-specific handling
needed in `app.main`).

`SAPRequestError` carries the parsed SAP error code/message (SAP's
error body shape is `{"error": {"code": <int>, "message": {"value":
"<string>", "lang": "..."}}}`) so callers — especially
`SAPIntegrationAgent`, which explains failures to a human — have
something concrete to reason about instead of a generic HTTP status.
"""

from __future__ import annotations

from app.core.exceptions import ExternalServiceError


class SAPAuthenticationError(ExternalServiceError):
    """Login to the Service Layer failed — bad credentials, wrong
    CompanyDB, or the Service Layer itself is unreachable/misconfigured."""

    error_code = "sap_authentication_error"


class SAPRequestError(ExternalServiceError):
    """A Service Layer request completed but returned an error body.
    `details` includes `sap_error_code` and `sap_error_message` when SAP
    provided them, plus `status_code` and `resource`."""

    error_code = "sap_request_error"

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        resource: str,
        sap_error_code: int | None = None,
        sap_error_message: str | None = None,
    ) -> None:
        super().__init__(
            message,
            details={
                "status_code": status_code,
                "resource": resource,
                "sap_error_code": sap_error_code,
                "sap_error_message": sap_error_message,
            },
        )
        self.status_code = status_code
        self.resource = resource
        self.sap_error_code = sap_error_code
        self.sap_error_message = sap_error_message


class SAPSessionExpiredError(SAPAuthenticationError):
    """Raised internally when a request comes back 401 after the client
    already attempted one re-login — signals a persistent auth problem
    rather than the routine session-timeout case (which the client
    handles transparently by re-logging in once)."""

    error_code = "sap_session_expired"


class SAPTransportError(ExternalServiceError):
    """A retry-safe SAP read failed after its bounded transport retries."""

    error_code = "sap_transport_error"


class SAPPotentialDuplicateError(ExternalServiceError):
    """A mutating SAP request has an unknown outcome. Never auto-retry it."""

    error_code = "sap_potential_duplicate"

    def __init__(self, message: str, *, method: str, resource: str) -> None:
        super().__init__(
            message,
            details={
                "method": method,
                "resource": resource,
                "retry_safe": False,
                "reconciliation_required": True,
            },
        )
