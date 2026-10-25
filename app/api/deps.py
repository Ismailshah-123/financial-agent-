"""Shared FastAPI authentication and authorization dependencies.

JWTs carry an immutable subject and optional compatibility claims, but the
server resolves the user from PostgreSQL for every protected request. The
stored account status and current role are therefore authoritative and a
revoked/deactivated account cannot continue using an already-issued token.
"""

from __future__ import annotations

from fastapi import Depends, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import Permission, UserRole
from app.core.exceptions import AuthenticationError, InsufficientPermissionsError
from app.core.security import TokenType, decode_token, role_has_permission
from app.db.session import get_db
from app.repositories.user_repository import UserRepository


class ActorContext(BaseModel):
    user_id: str
    role: UserRole
    permissions: list[Permission]
    is_dev_token: bool = False


async def get_current_actor(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> ActorContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError(
            "Missing or malformed Authorization header. Expected 'Bearer <token>'."
        )
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token, expected_type=TokenType.ACCESS)
    actor = _actor_from_token_payload(payload)
    return await _resolve_authoritative_actor(actor, session)


def _actor_from_token_payload(payload: dict) -> ActorContext:
    """Parse token identity while treating persisted role/permissions as authoritative."""
    try:
        role = UserRole(payload["role"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Token is missing a valid role claim.") from exc

    raw_permissions = payload.get("permissions", [])
    valid_values = {p.value for p in Permission}
    permissions = [Permission(p) for p in raw_permissions if p in valid_values]
    return ActorContext(
        user_id=str(payload.get("sub", "")),
        role=role,
        permissions=permissions,
        is_dev_token=bool(payload.get("dev_token", False)),
    )


async def _resolve_authoritative_actor(
    actor: ActorContext, session: AsyncSession
) -> ActorContext:
    if actor.is_dev_token:
        if settings.app.environment.value not in {"local", "development", "test"}:
            raise AuthenticationError("Development tokens are not accepted in this environment.")
        return actor

    try:
        import uuid

        user_id = uuid.UUID(actor.user_id)
    except (ValueError, AttributeError) as exc:
        raise AuthenticationError("Token subject is not a valid user id.") from exc

    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is no longer available.")
    try:
        role = UserRole(user.role)
    except ValueError as exc:
        raise AuthenticationError("Account has an invalid role configuration.") from exc
    return ActorContext(
        user_id=str(user.id),
        role=role,
        permissions=sorted(_role_permissions_for_role(role), key=lambda p: p.value),
    )


def _role_permissions_for_role(role: UserRole) -> set[Permission]:
    # Localized import avoids a core-security -> API dependency cycle.
    from app.core.security import ROLE_PERMISSIONS

    return ROLE_PERMISSIONS.get(role, set())


def require_permission(permission: Permission):
    """Require a permission from the authoritative persisted user role."""

    async def _dependency(
        actor: ActorContext = Depends(get_current_actor),
    ) -> ActorContext:
        if not role_has_permission(actor.role, permission):
            raise InsufficientPermissionsError(
                f"Actor '{actor.user_id}' (role '{actor.role.value}') lacks "
                f"permission '{permission.value}'."
            )
        return actor

    return _dependency
