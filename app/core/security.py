"""
app.core.security
==================
Authentication and authorization primitives:

    - Password hashing (bcrypt via passlib)
    - JWT access/refresh token issuance and verification
    - Opaque API key generation and verification (for service-to-service
      and SAP-integration callers that shouldn't use short-lived JWTs)
    - RBAC permission checks + an ABAC hook for attribute-based rules
      (approval limits, department scoping) evaluated on top of roles

WHAT'S DELIBERATELY NOT HERE YET
----------------------------------
MFA (TOTP) enrollment/verification, Azure AD / Google OAuth code exchange,
and session/device management are Phase 1.x additions that build on top
of this module once the user/session DB models exist (next step in the
compatibility-audit order: core -> db -> schemas -> ...). Stubbing them
here with fake logic would be worse than not having them yet, so this
file only contains primitives that are fully correct today.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.constants import Permission, UserRole
from app.core.exceptions import (
    AuthorizationError,
    InsufficientPermissionsError,
    InvalidCredentialsError,
    TokenExpiredError,
)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------
def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def _create_token(
    *,
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),  # unique id -> enables server-side revocation lists
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.security.jwt_secret_key.get_secret_value(),
        algorithm=settings.security.jwt_algorithm,
    )


def create_access_token(
    *,
    user_id: str,
    role: UserRole,
    permissions: list[Permission] | None = None,
    dev_token: bool = False,
) -> str:
    return _create_token(
        subject=user_id,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.security.access_token_expire_minutes),
        extra_claims={
            "role": role.value,
            "permissions": [p.value for p in (permissions or [])],
            "dev_token": dev_token,
        },
    )


def create_refresh_token(*, user_id: str) -> str:
    return _create_token(
        subject=user_id,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.security.refresh_token_expire_days),
    )


def token_jti(payload: dict[str, Any]) -> str:
    """Return a validated JWT id required for persisted session tracking."""
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise InvalidCredentialsError("Token is missing a valid session identifier.")
    return jti


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a JWT. Raises TokenExpiredError /
    InvalidCredentialsError — callers should not need to know about
    the `jwt` library's own exception types."""
    try:
        payload = jwt.decode(
            token,
            settings.security.jwt_secret_key.get_secret_value(),
            algorithms=[settings.security.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidCredentialsError("Token is invalid.") from exc

    if payload.get("type") != expected_type.value:
        raise InvalidCredentialsError(
            f"Expected a {expected_type.value} token, got {payload.get('type')}."
        )
    return payload


# --------------------------------------------------------------------------
# API keys (service-to-service / SAP integration callers)
# --------------------------------------------------------------------------
def generate_api_key() -> tuple[str, str]:
    """
    Returns (plaintext_key, hashed_key). Only the hash is stored; the
    plaintext is shown to the user exactly once at creation time — this
    mirrors how Stripe/GitHub API keys work and means a DB leak alone
    cannot be used to authenticate.
    """
    plaintext = f"{settings.security.api_key_prefix}{secrets.token_urlsafe(32)}"
    hashed = _pwd_context.hash(plaintext)
    return plaintext, hashed


def verify_api_key(plaintext_key: str, hashed_key: str) -> bool:
    return _pwd_context.verify(plaintext_key, hashed_key)


# --------------------------------------------------------------------------
# RBAC / ABAC authorization
# --------------------------------------------------------------------------
# Default role -> permission grants. This is the RBAC baseline; ABAC
# rules (e.g. "approver limit >= invoice amount", "same department only")
# are evaluated separately per-resource in the service layer using
# `check_attribute_rule` below, on top of whatever RBAC allows.
ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.SUPER_ADMIN: set(Permission),
    UserRole.FINANCE_DIRECTOR: {
        Permission.VENDOR_READ,
        Permission.VENDOR_MANAGE,
        Permission.VENDOR_BANK_DETAILS_READ,
        Permission.PURCHASE_ORDER_READ,
        Permission.INVOICE_READ,
        Permission.INVOICE_APPROVE,
        Permission.PAYMENT_READ,
        Permission.PAYMENT_APPROVE,
        Permission.JOURNAL_ENTRY_POST,
        Permission.REPORT_VIEW,
        Permission.REPORT_EXPORT,
        Permission.AGENT_INVOKE,
        Permission.AGENT_CONFIGURE,
        Permission.AUDIT_LOG_READ,
        Permission.CUSTOMER_READ,
        Permission.CUSTOMER_MANAGE,
        Permission.AR_INVOICE_READ,
        Permission.AR_INVOICE_APPROVE,
        Permission.CREDIT_MEMO_READ,
        Permission.CREDIT_MEMO_APPROVE,
        Permission.TAX_CODE_READ,
        Permission.TAX_CODE_MANAGE,
        Permission.PERIOD_CLOSE_READ,
        Permission.PERIOD_CLOSE_EXECUTE,
        Permission.BANK_STATEMENT_READ,
        Permission.BANK_STATEMENT_INGEST,
        Permission.BANK_STATEMENT_MATCH,
        Permission.BUDGET_READ,
        Permission.BUDGET_MANAGE,
        Permission.FBR_REMITTANCE_READ,
        Permission.FBR_REMITTANCE_RECORD,
        Permission.APPROVAL_REQUEST_READ,
        Permission.APPROVAL_REQUEST_ACTION,
    },
    UserRole.FINANCE_MANAGER: {
        Permission.VENDOR_READ,
        Permission.VENDOR_CREATE,
        Permission.PURCHASE_ORDER_READ,
        Permission.PURCHASE_ORDER_CREATE,
        Permission.INVOICE_READ,
        Permission.INVOICE_APPROVE,
        Permission.PAYMENT_READ,
        Permission.JOURNAL_ENTRY_CREATE,
        Permission.REPORT_VIEW,
        Permission.AGENT_INVOKE,
        Permission.CUSTOMER_READ,
        Permission.CUSTOMER_CREATE,
        Permission.AR_INVOICE_READ,
        Permission.AR_INVOICE_APPROVE,
        Permission.CREDIT_MEMO_READ,
        Permission.CREDIT_MEMO_APPROVE,
        Permission.TAX_CODE_READ,
        Permission.PERIOD_CLOSE_READ,
        Permission.BANK_STATEMENT_READ,
        Permission.BANK_STATEMENT_INGEST,
        Permission.BANK_STATEMENT_MATCH,
        Permission.BUDGET_READ,
        Permission.BUDGET_MANAGE,
        Permission.FBR_REMITTANCE_READ,
        Permission.FBR_REMITTANCE_RECORD,
        Permission.APPROVAL_REQUEST_READ,
        Permission.APPROVAL_REQUEST_ACTION,
    },
    UserRole.ACCOUNTANT: {
        Permission.VENDOR_READ,
        Permission.PURCHASE_ORDER_READ,
        Permission.INVOICE_READ,
        Permission.INVOICE_CREATE,
        Permission.JOURNAL_ENTRY_CREATE,
        Permission.REPORT_VIEW,
        Permission.AGENT_INVOKE,
        Permission.CUSTOMER_READ,
        Permission.AR_INVOICE_READ,
        Permission.AR_INVOICE_CREATE,
        Permission.CREDIT_MEMO_READ,
        Permission.CREDIT_MEMO_CREATE,
        Permission.TAX_CODE_READ,
        Permission.PERIOD_CLOSE_READ,
        Permission.BANK_STATEMENT_READ,
        Permission.BANK_STATEMENT_INGEST,
        Permission.BANK_STATEMENT_MATCH,
        Permission.BUDGET_READ,
        Permission.FBR_REMITTANCE_READ,
        Permission.APPROVAL_REQUEST_READ,
    },
    UserRole.AP_CLERK: {
        Permission.VENDOR_READ,
        Permission.VENDOR_CREATE,
        Permission.PURCHASE_ORDER_READ,
        Permission.PURCHASE_ORDER_CREATE,
        Permission.GOODS_RECEIPT_CREATE,
        Permission.INVOICE_READ,
        Permission.INVOICE_CREATE,
        Permission.PAYMENT_READ,
        Permission.PAYMENT_INITIATE,
        Permission.AGENT_INVOKE,
        Permission.CREDIT_MEMO_READ,
        Permission.CREDIT_MEMO_CREATE,
        Permission.TAX_CODE_READ,
    },
    UserRole.AR_CLERK: {
        Permission.VENDOR_READ,
        Permission.INVOICE_READ,
        Permission.PAYMENT_READ,
        Permission.PAYMENT_INITIATE,
        Permission.AGENT_INVOKE,
        Permission.CUSTOMER_READ,
        Permission.CUSTOMER_CREATE,
        Permission.AR_INVOICE_READ,
        Permission.AR_INVOICE_CREATE,
        Permission.CREDIT_MEMO_READ,
        Permission.CREDIT_MEMO_CREATE,
        Permission.TAX_CODE_READ,
    },
    UserRole.AUDITOR: {
        Permission.VENDOR_READ,
        Permission.PURCHASE_ORDER_READ,
        Permission.INVOICE_READ,
        Permission.PAYMENT_READ,
        Permission.REPORT_VIEW,
        Permission.AUDIT_LOG_READ,
        Permission.CUSTOMER_READ,
        Permission.AR_INVOICE_READ,
        Permission.CREDIT_MEMO_READ,
        Permission.TAX_CODE_READ,
        Permission.PERIOD_CLOSE_READ,
        Permission.BANK_STATEMENT_READ,
        Permission.BUDGET_READ,
        Permission.FBR_REMITTANCE_READ,
        Permission.APPROVAL_REQUEST_READ,
    },
    UserRole.APPROVER: {
        Permission.VENDOR_READ,
        Permission.PURCHASE_ORDER_READ,
        Permission.INVOICE_READ,
        Permission.INVOICE_APPROVE,
        Permission.PAYMENT_READ,
        Permission.PAYMENT_APPROVE,
        Permission.CUSTOMER_READ,
        Permission.AR_INVOICE_READ,
        Permission.AR_INVOICE_APPROVE,
        Permission.CREDIT_MEMO_READ,
        Permission.CREDIT_MEMO_APPROVE,
        Permission.TAX_CODE_READ,
        Permission.APPROVAL_REQUEST_READ,
        Permission.APPROVAL_REQUEST_ACTION,
    },
    UserRole.VIEWER: {
        Permission.VENDOR_READ,
        Permission.PURCHASE_ORDER_READ,
        Permission.INVOICE_READ,
        Permission.PAYMENT_READ,
        Permission.REPORT_VIEW,
        Permission.CUSTOMER_READ,
        Permission.AR_INVOICE_READ,
        Permission.CREDIT_MEMO_READ,
        Permission.TAX_CODE_READ,
    },
}


def role_has_permission(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def require_permission(role: UserRole, permission: Permission) -> None:
    if not role_has_permission(role, permission):
        raise InsufficientPermissionsError(
            f"Role '{role.value}' lacks permission '{permission.value}'."
        )


def check_attribute_rule(*, condition: bool, message: str) -> None:
    """
    ABAC hook: pass the already-evaluated boolean condition for a specific
    resource (e.g. `approver.approval_limit >= invoice.amount`, or
    `user.department_id == invoice.department_id`). Kept generic and
    resource-agnostic here; concrete rules live next to the domain models
    once those exist (app/services/*), since this module must not import
    domain entities.
    """
    if not condition:
        raise AuthorizationError(message)
