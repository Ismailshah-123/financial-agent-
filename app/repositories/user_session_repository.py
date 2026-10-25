from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.models.user_session import UserSession
from app.repositories.base_repository import BaseRepository


class UserSessionRepository(BaseRepository[UserSession]):
    model = UserSession

    async def get_by_refresh_jti(self, refresh_jti: str) -> UserSession | None:
        stmt = self._base_select().where(UserSession.refresh_jti == refresh_jti)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_refresh_jti_for_update(self, refresh_jti: str) -> UserSession | None:
        stmt = self._base_select().where(UserSession.refresh_jti == refresh_jti).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        sessions = await self.session.execute(
            select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None)).with_for_update()
        )
        rows = list(sessions.scalars().all())
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        for row in rows:
            row.revoked_at = now
        await self.session.flush()
        return len(rows)
