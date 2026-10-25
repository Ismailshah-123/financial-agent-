"""
app.repositories.period_close_repository
============================================
`PeriodClose`-specific data access. The one genuinely domain-specific
query here is `list_overlapping`: `PeriodCloseService.close_period`
needs to reject a close whose date range overlaps any existing,
still-in-effect (not reopened) close — see that service's docstring
for the exact rule.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.db.models.period_close import PeriodClose
from app.repositories.base_repository import BaseRepository


class PeriodCloseRepository(BaseRepository[PeriodClose]):
    model = PeriodClose

    async def list_overlapping(
        self, *, start_date: date, end_date: date
    ) -> list[PeriodClose]:
        """Active (is_reopened=False) closes whose range intersects
        [start_date, end_date]. Standard interval-overlap test: two
        ranges do NOT overlap iff one ends before the other starts."""
        stmt = self._base_select().where(
            PeriodClose.is_reopened.is_(False),
            PeriodClose.start_date <= end_date,
            PeriodClose.end_date >= start_date,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_close(self) -> PeriodClose | None:
        """Most recent active close by end_date, or None if nothing's
        been closed yet. Used to enforce closing periods in order (no
        closing March before February)."""
        stmt = (
            self._base_select()
            .where(PeriodClose.is_reopened.is_(False))
            .order_by(PeriodClose.end_date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
