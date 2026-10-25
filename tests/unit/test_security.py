"""
Unit tests for app.core.security — password hashing, JWT issuance/
verification (including expiry and wrong-token-type rejection), API key
generation, and RBAC permission checks.
"""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.constants import Permission, UserRole
from app.core.exceptions import InsufficientPermissionsError, TokenExpiredError
from app.core.security import (
    TokenType,
    _create_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    hash_password,
    require_permission,
    verify_api_key,
    verify_password,
)


def test_password_hash_round_trip() -> None:
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_round_trip() -> None:
    token = create_access_token(
        user_id="user-123",
        role=UserRole.ACCOUNTANT,
        permissions=[Permission.INVOICE_READ],
    )
    payload = decode_token(token, expected_type=TokenType.ACCESS)
    assert payload["sub"] == "user-123"
    assert payload["role"] == UserRole.ACCOUNTANT.value
    assert Permission.INVOICE_READ.value in payload["permissions"]


def test_refresh_token_rejected_as_access_token() -> None:
    token = create_refresh_token(user_id="user-123")
    with pytest.raises(Exception):
        decode_token(token, expected_type=TokenType.ACCESS)


def test_expired_token_raises_token_expired_error() -> None:
    token = _create_token(
        subject="user-123",
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(seconds=-1),
    )
    with pytest.raises(TokenExpiredError):
        decode_token(token, expected_type=TokenType.ACCESS)


def test_api_key_round_trip() -> None:
    plaintext, hashed = generate_api_key()
    assert plaintext.startswith(settings.security.api_key_prefix)
    assert verify_api_key(plaintext, hashed)
    assert not verify_api_key("not-the-key", hashed)


def test_require_permission_passes_for_granted_permission() -> None:
    require_permission(UserRole.FINANCE_DIRECTOR, Permission.INVOICE_APPROVE)


def test_require_permission_raises_for_missing_permission() -> None:
    with pytest.raises(InsufficientPermissionsError):
        require_permission(UserRole.VIEWER, Permission.PAYMENT_APPROVE)


def test_vendor_bank_details_permission_is_restricted_to_trusted_roles() -> None:
    from app.core.security import role_has_permission

    permission = Permission.VENDOR_BANK_DETAILS_READ
    assert role_has_permission(UserRole.SUPER_ADMIN, permission)
    assert role_has_permission(UserRole.FINANCE_DIRECTOR, permission)
    assert not role_has_permission(UserRole.FINANCE_MANAGER, permission)
    assert not role_has_permission(UserRole.ACCOUNTANT, permission)
    assert not role_has_permission(UserRole.AUDITOR, permission)
    assert not role_has_permission(UserRole.AP_CLERK, permission)
    assert not role_has_permission(UserRole.AR_CLERK, permission)
    assert not role_has_permission(UserRole.APPROVER, permission)
    assert not role_has_permission(UserRole.VIEWER, permission)


def test_sap_master_data_sync_requires_agent_configure_permission() -> None:
    """Only trusted roles receive the permission used by the SAP sync route."""
    from app.core.security import role_has_permission

    assert role_has_permission(UserRole.SUPER_ADMIN, Permission.AGENT_CONFIGURE)
    assert role_has_permission(UserRole.FINANCE_DIRECTOR, Permission.AGENT_CONFIGURE)
    for role in (
        UserRole.FINANCE_MANAGER,
        UserRole.ACCOUNTANT,
        UserRole.AP_CLERK,
        UserRole.AR_CLERK,
        UserRole.APPROVER,
        UserRole.AUDITOR,
        UserRole.VIEWER,
    ):
        assert not role_has_permission(role, Permission.AGENT_CONFIGURE)
