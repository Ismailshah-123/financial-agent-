"""
app.services.auth_service
=========================
Authentication use-cases with persisted refresh-token sessions.

Access tokens remain short-lived JWTs. Refresh tokens are rotated on every
successful exchange and each refresh token is bound to a persisted session
record keyed by JWT `jti`. Logout revokes the current refresh session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import UserRole
from app.core.exceptions import ConflictError, InvalidCredentialsError
from app.core.logging import get_audit_logger, get_logger
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_jti,
    verify_password,
)
from app.db.models.user import User
from app.db.models.user_session import UserSession
from app.repositories.user_repository import UserRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.schemas.auth import LogoutResponse, TokenResponse
from app.schemas.user import UserCreate

logger = get_logger(__name__)

_DUMMY_HASH = hash_password("not-a-real-password-used-only-for-timing-safety")


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = UserRepository(session)
        self.session_repository = UserSessionRepository(session)

    async def register(self, payload: UserCreate) -> User:
        existing = await self.repository.get_by_email(payload.email)
        if existing is not None:
            raise ConflictError(f"A user with email '{payload.email}' already exists.")

        user = User(
            email=payload.email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
            role=payload.role.value,
            is_active=True,
        )
        user = await self.repository.add(user)
        await get_audit_logger().record(
            session=self.session,
            actor_id=str(user.id),
            action="user.register",
            resource_type="user",
            resource_id=str(user.id),
            outcome="success",
            metadata={"email": user.email, "role": user.role},
        )
        logger.info("user_registered", user_id=str(user.id), email=user.email)
        return user

    async def authenticate(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenResponse:
        user = await self.repository.get_by_email(email)
        if user is None:
            verify_password(password, _DUMMY_HASH)
            raise InvalidCredentialsError("Invalid email or password.")

        if not verify_password(password, user.hashed_password):
            await get_audit_logger().record(
                session=self.session,
                actor_id=str(user.id),
                action="user.login",
                resource_type="user",
                resource_id=str(user.id),
                outcome="failed",
            )
            raise InvalidCredentialsError("Invalid email or password.")

        if not user.is_active:
            raise InvalidCredentialsError("This account has been deactivated.")

        access_token = create_access_token(user_id=str(user.id), role=UserRole(user.role))
        refresh_token = create_refresh_token(user_id=str(user.id))
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
        now = datetime.now(timezone.utc)
        session_row = UserSession(
            user_id=user.id,
            refresh_jti=token_jti(payload),
            expires_at=_as_datetime(payload["exp"]),
            last_used_at=now,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await self.session_repository.add(session_row)
        await get_audit_logger().record(
            session=self.session,
            actor_id=str(user.id),
            action="user.login",
            resource_type="user",
            resource_id=str(user.id),
            outcome="success",
            metadata={"session_id": str(session_row.id)},
        )
        logger.info("user_authenticated", user_id=str(user.id), session_id=str(session_row.id))
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.security.access_token_expire_minutes * 60,
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
        refresh_jti = token_jti(payload)
        session_row = await self.session_repository.get_by_refresh_jti_for_update(refresh_jti)
        if session_row is None:
            raise InvalidCredentialsError("Refresh session is no longer available.")
        if session_row.revoked_at is not None:
            raise InvalidCredentialsError("Refresh session has been revoked.")
        if session_row.expires_at <= datetime.now(timezone.utc):
            session_row.revoked_at = datetime.now(timezone.utc)
            await self.session.flush()
            raise InvalidCredentialsError("Refresh session has expired.")

        user = await self.repository.get_by_id(session_row.user_id)
        if user is None or not user.is_active:
            session_row.revoked_at = datetime.now(timezone.utc)
            await self.session.flush()
            raise InvalidCredentialsError("Account no longer available.")

        new_access_token = create_access_token(user_id=str(user.id), role=UserRole(user.role))
        new_refresh_token = create_refresh_token(user_id=str(user.id))
        new_payload = decode_token(new_refresh_token, expected_type=TokenType.REFRESH)
        now = datetime.now(timezone.utc)
        session_row.revoked_at = now
        session_row.last_used_at = now
        replacement = UserSession(
            user_id=user.id,
            refresh_jti=token_jti(new_payload),
            expires_at=_as_datetime(new_payload["exp"]),
            last_used_at=now,
            user_agent=session_row.user_agent,
            ip_address=session_row.ip_address,
        )
        await self.session_repository.add(replacement)
        await get_audit_logger().record(
            session=self.session,
            actor_id=str(user.id),
            action="user.refresh",
            resource_type="user_session",
            resource_id=str(replacement.id),
            outcome="success",
            metadata={"replaced_session_id": str(session_row.id)},
        )
        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in=settings.security.access_token_expire_minutes * 60,
        )

    async def logout(self, refresh_token: str, *, actor_id: str | None = None) -> LogoutResponse:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
        refresh_jti = token_jti(payload)
        session_row = await self.session_repository.get_by_refresh_jti_for_update(refresh_jti)
        if session_row is None:
            # Treat unknown session as already revoked for an idempotent logout.
            return LogoutResponse(revoked=True)
        if session_row.revoked_at is None:
            session_row.revoked_at = datetime.now(timezone.utc)
            await self.session.flush()
            await get_audit_logger().record(
                session=self.session,
                actor_id=actor_id or str(session_row.user_id),
                action="user.logout",
                resource_type="user_session",
                resource_id=str(session_row.id),
                outcome="success",
            )
        return LogoutResponse(revoked=True)


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    raise InvalidCredentialsError("Token expiry is invalid.")
