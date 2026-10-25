"""
app.repositories.budget_repository
======================================
`Budget` data access. `list_overlapping` exists for the same reason
`PeriodCloseRepository.list_overlapping` does — catching an accidental
duplicate budget (same account, overlapping period) at creation time
rather than silently allowing two conflicting targets for the same
account/period to coexist.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.db.models.budget import Budget
from app.repositories.base_repository import BaseRepository


class BudgetRepository(BaseRepository[Budget]):
    model = Budget

    async def list_overlapping(
        self, *, account_code: str, period_start: date, period_end: date
    ) -> list[Budget]:
        stmt = self._base_select().where(
            Budget.account_code == account_code,
            Budget.period_start <= period_end,
            Budget.period_end >= period_start,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all_for_period(self, *, period_start: date, period_end: date) -> list[Budget]:
        """Every budget (any account) overlapping [period_start,
        period_end] — the account-agnostic sibling of list_overlapping,
        which exists to check ONE account before creating a new budget.
        This one exists for FinanceDirectorAgent's period review, which
        needs to discover every budget worth checking, not validate one
        specific new one."""
        stmt = self._base_select().where(
            Budget.period_start <= period_end,
            Budget.period_end >= period_start,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
