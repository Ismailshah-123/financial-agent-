"""
app.db.models.user
====================
The `User` record — the piece that was deliberately deferred until now
(see `app.api.deps` docstring on why auth was JWT-claim-only up to this
point). Every other model's `created_by_id`/`updated_by_id`
(`AuditMixin`) is a foreign key onto this table's `id` in spirit, though
not enforced as a literal FK constraint here — enforcing it would create
a circular migration-ordering dependency (every audited table would need
`users` to exist first, and `users` itself uses `AuditMixin`, e.g. an
admin creating another user). Left as a plain UUID column, consistent
with how `AuditMixin` is documented in `app.db.base`.

`hashed_password` is set via `app.core.security.hash_password` — never
store or compare plaintext passwords, and never log this column (it
isn't included in any `UserRead` schema).

`role` is the RBAC baseline (`app.core.constants.UserRole`); nothing on
this model grants permissions beyond what that role provides in
`app.core.security.ROLE_PERMISSIONS` — if a deployment needs a
user-specific permission override beyond their role, that's a
deliberately separate, more carefully audited feature to add later
(narrowly-scoped API-key tokens already support this pattern at the
token level — see `app.api.deps.require_permission`).
"""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import UserRole
from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, AuditMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        String(32), nullable=False, default=UserRole.VIEWER.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} email={self.email!r} role={self.role}>"
