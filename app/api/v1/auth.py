"""Authentication and persisted session lifecycle endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, get_current_actor
from app.core.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.db.session import get_db
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, LogoutResponse, RefreshRequest, TokenResponse
from app.schemas.user import UserCreate, UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=UserRead)
async def me(
    actor: ActorContext = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db),
) -> UserRead:
    user = await UserRepository(session).get_by_id(uuid.UUID(actor.user_id))
    if user is None or not user.is_active:
        raise AuthenticationError("Account is no longer available.")
    return UserRead.from_user(user)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate, session: AsyncSession = Depends(get_db)
) -> UserRead:
    if not settings.security.allow_public_registration:
        raise AuthorizationError("Public registration is disabled for this deployment.")
    service = AuthService(session)
    user = await service.register(payload)
    await session.commit()
    return UserRead.from_user(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    service = AuthService(session)
    try:
        response = await service.authenticate(
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
        await session.commit()
        return response
    except AuthenticationError:
        # Preserve security/audit events even though the request itself is an auth failure.
        await session.commit()
        raise


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest, session: AsyncSession = Depends(get_db)
) -> TokenResponse:
    service = AuthService(session)
    response = await service.refresh(payload.refresh_token)
    await session.commit()
    return response


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> LogoutResponse:
    service = AuthService(session)
    response = await service.logout(
        payload.refresh_token,
    )
    await session.commit()
    return response
