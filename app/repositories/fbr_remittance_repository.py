"""
app.repositories.fbr_remittance_repository
==============================================
`FBRRemittance` data access. `list_overlapping` returns every
remittance touching a given range — deliberately NOT deduplicated to
one-per-period, since a company might file more than one remittance
within the same window (e.g. a correction). `FBRComplianceService`
sums whatever comes back.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.db.models.fbr_remittance import FBRRemittance
from app.repositories.base_repository import BaseRepository


class FBRRemittanceRepository(BaseRepository[FBRRemittance]):
    model = FBRRemittance

    async def list_overlapping(
        self, *, period_start: date, period_end: date
    ) -> list[FBRRemittance]:
        stmt = self._base_select().where(
            FBRRemittance.period_start <= period_end,
            FBRRemittance.period_end >= period_start,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
