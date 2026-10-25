"""
Unit tests for app.api.deps — get_current_actor (JWT parsing into an
ActorContext) and require_permission (the permission-gating dependency
factory). Called directly as plain async functions rather than through
a running FastAPI app/TestClient, since these are pure functions once
you supply the header string / ActorContext they expect.
"""

from __future__ import annotations

import pytest

from app.api.deps import get_current_actor, require_permission
from app.core.constants import Permission, UserRole
from app.core.exceptions import AuthenticationError, InsufficientPermissionsError
from app.core.security import create_access_token


async def test_valid_bearer_token_resolves_actor_context() -> None:
    token = create_access_token(
        user_id="user-1", role=UserRole.AP_CLERK, permissions=[Permission.INVOICE_READ]
    )
    actor = await get_current_actor(authorization=f"Bearer {token}")
    assert actor.user_id == "user-1"
    assert actor.role == UserRole.AP_CLERK
    assert Permission.INVOICE_READ in actor.permissions


async def test_missing_authorization_header_raises() -> None:
    with pytest.raises(AuthenticationError):
        await get_current_actor(authorization=None)


async def test_malformed_authorization_header_raises() -> None:
    with pytest.raises(AuthenticationError):
        await get_current_actor(authorization="NotBearer sometoken")


async def test_require_permission_allows_role_with_rbac_grant() -> None:
    token = create_access_token(user_id="user-2", role=UserRole.FINANCE_DIRECTOR)
    actor = await get_current_actor(authorization=f"Bearer {token}")
    dependency = require_permission(Permission.INVOICE_APPROVE)
    result = await dependency(actor=actor)
    assert result is actor


async def test_require_permission_rejects_role_without_grant() -> None:
    token = create_access_token(user_id="user-3", role=UserRole.VIEWER)
    actor = await get_current_actor(authorization=f"Bearer {token}")
    dependency = require_permission(Permission.PAYMENT_APPROVE)
    with pytest.raises(InsufficientPermissionsError):
        await dependency(actor=actor)


async def test_require_permission_allows_via_explicit_token_permission() -> None:
    """A VIEWER role doesn't get PAYMENT_APPROVE via RBAC, but a token
    that explicitly lists it (a narrowly-scoped service token) should
    still pass — see require_permission's docstring."""
    token = create_access_token(
        user_id="user-4",
        role=UserRole.VIEWER,
        permissions=[Permission.PAYMENT_APPROVE],
    )
    actor = await get_current_actor(authorization=f"Bearer {token}")
    dependency = require_permission(Permission.PAYMENT_APPROVE)
    result = await dependency(actor=actor)
    assert result is actor
