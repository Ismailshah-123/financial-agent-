"""
app.schemas.user
==================
Request/response shapes for User accounts. `UserCreate.password` is
plaintext ONLY in transit (over TLS) — `AuthService.register` hashes it
immediately via `app.core.security.hash_password` before it ever touches
the database, and `UserRead` deliberately has no password field at all,
so it is structurally impossible for a hash (let alone plaintext) to
leak through any endpoint that returns a `UserRead`.
"""

from __future__ import annotations

import uuid

from pydantic import EmailStr, Field

from app.core.constants import Permission, UserRole
from app.schemas.common import APIModel


class UserCreate(APIModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.VIEWER


class UserRead(APIModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    permissions: list[Permission] = Field(default_factory=list)

    @classmethod
    def from_user(cls, user) -> "UserRead":
        from app.core.security import ROLE_PERMISSIONS

        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=UserRole(user.role),
            is_active=user.is_active,
            permissions=sorted(ROLE_PERMISSIONS.get(UserRole(user.role), set()), key=lambda p: p.value),
        )
