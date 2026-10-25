"""
app.repositories.tax_code_repository
=======================================
Tax Code data access. `get_effective_rate` is the core lookup
`TaxCalculationService` depends on: given a logical `code` and a date,
find the one row (of possibly several historical rows sharing that
code) whose effective range actually covers that date. See
`app.db.models.tax_code.TaxCode`'s docstring for why rates are
effective-dated rather than a single current value.
"""

from __future__ import annotations

from datetime import date

from app.db.models.tax_code import TaxCode
from app.repositories.base_repository import BaseRepository


class TaxCodeRepository(BaseRepository[TaxCode]):
    model = TaxCode

    async def get_effective_rate(self, *, code: str, as_of: date) -> TaxCode | None:
        candidates = await self.list_by_code(code)
        for candidate in candidates:
            if candidate.is_active and candidate.covers(as_of):
                return candidate
        return None

    async def list_by_code(self, code: str) -> list[TaxCode]:
        stmt = self._base_select().where(TaxCode.code == code)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self) -> list[TaxCode]:
        stmt = self._base_select().where(TaxCode.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
