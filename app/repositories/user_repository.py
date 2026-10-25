"""
app.repositories.user_repository
===================================
User data access. `get_by_email` is the one lookup the whole auth flow
depends on (`AuthService.authenticate` calls it first, before touching
`hashed_password` at all).
"""

from __future__ import annotations

from app.db.models.user import User
from app.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        stmt = self._base_select().where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
