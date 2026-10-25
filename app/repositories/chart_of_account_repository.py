"""
app.repositories.chart_of_account_repository
===============================================
Chart of Accounts data access. `list_all_active` and `get_by_code` are
what `FinancialReportingService` uses to classify every journal entry
line it aggregates — see that service's docstring for what happens when
a posted account code has no matching row here (it raises, rather than
silently excluding the account from a report).
"""

from __future__ import annotations

from app.db.models.chart_of_account import ChartOfAccount
from app.repositories.base_repository import BaseRepository


class ChartOfAccountRepository(BaseRepository[ChartOfAccount]):
    model = ChartOfAccount

    async def get_by_code(self, account_code: str) -> ChartOfAccount | None:
        stmt = self._base_select().where(ChartOfAccount.account_code == account_code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all_active(self) -> list[ChartOfAccount]:
        stmt = self._base_select().where(ChartOfAccount.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
