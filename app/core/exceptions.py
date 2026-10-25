"""
app.core.exceptions
====================
Single exception hierarchy for the whole platform, mapped to HTTP status
codes and machine-readable error codes at one place (app.main's exception
handlers), instead of every route inventing its own error shape.

DESIGN
------
Every exception carries:
    - `error_code`: stable, machine-readable string (safe to key client-side
      error handling off of; will not change even if the human message does)
    - `http_status`: the status code the API layer should return
    - `details`: optional structured payload (validation field errors,
      the offending resource id, etc.)

`BaseAppException` is intentionally the only class other modules should
catch broadly (`except BaseAppException`) when they want to convert any
platform error into an API response. Catching bare `Exception` anywhere
in business logic is a code-review flag.
"""

from __future__ import annotations

from typing import Any


class BaseAppException(Exception):
    """Root of the platform's exception hierarchy."""

    error_code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


# --------------------------------------------------------------------------
# 4xx — client errors
# --------------------------------------------------------------------------
class ValidationError(BaseAppException):
    error_code = "validation_error"
    http_status = 422


class AuthenticationError(BaseAppException):
    error_code = "authentication_error"
    http_status = 401


class InvalidCredentialsError(AuthenticationError):
    error_code = "invalid_credentials"


class TokenExpiredError(AuthenticationError):
    error_code = "token_expired"


class AuthorizationError(BaseAppException):
    error_code = "authorization_error"
    http_status = 403


class InsufficientPermissionsError(AuthorizationError):
    error_code = "insufficient_permissions"


class NotFoundError(BaseAppException):
    error_code = "not_found"
    http_status = 404


class ConflictError(BaseAppException):
    error_code = "conflict"
    http_status = 409


class RateLimitExceededError(BaseAppException):
    error_code = "rate_limit_exceeded"
    http_status = 429


# --------------------------------------------------------------------------
# 5xx / domain — server & business-rule errors
# --------------------------------------------------------------------------
class ExternalServiceError(BaseAppException):
    """A downstream dependency (LLM provider, SAP, OCR service, broker)
    failed or timed out."""

    error_code = "external_service_error"
    http_status = 502


class AgentExecutionError(BaseAppException):
    """An agent failed mid-execution. Callers should check `details` for
    `agent_type`, `step`, and whether a rollback was triggered."""

    error_code = "agent_execution_error"
    http_status = 500


class ApprovalRequiredError(BaseAppException):
    """Raised when an agent attempts an action that requires human
    approval and none has been granted yet. Not a failure — the caller
    should surface this as "pending approval", not as an error toast."""

    error_code = "approval_required"
    http_status = 202


class PolicyViolationError(BaseAppException):
    """An agent decision would violate a configured financial policy
    (spending limit, segregation-of-duties rule, etc.)."""

    error_code = "policy_violation"
    http_status = 403


class RollbackFailedError(BaseAppException):
    """A compensating transaction failed after a prior step succeeded.
    Always treat as high-severity — this means manual reconciliation
    is required."""

    error_code = "rollback_failed"
    http_status = 500
