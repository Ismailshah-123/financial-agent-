"""
app.db.models.budget
========================
`Budget`: a spending or revenue target for one `account_code` over one
[period_start, period_end] range. References the account by its string
code (matching `TaxCode`/`PeriodClose`'s account-reference convention —
see `alembic/versions/0009_budget_planning.py`), not a foreign key.

WHAT A BUDGET IS NOT
------------------------
Not a journal entry, not something `PostingService` ever touches — a
Budget is a planning input, purely descriptive of a target. It's
compared against ACTUAL activity (via
`FinancialReportingService._account_balances` for the same account and
period) by `app.services.budget_service.BudgetService.compute_variance`,
never posted anywhere itself.

DIRECTION OF "OVER BUDGET" DEPENDS ON THE ACCOUNT'S TYPE
------------------------------------------------------------------
For an EXPENSE account, actual spend EXCEEDING `budgeted_amount` is the
bad direction. For a REVENUE account, actual revenue FALLING SHORT of
`budgeted_amount` (a target, not a cap) is the bad direction — see
`BudgetService.compute_variance` for how this flips based on the
target account's `AccountType`, looked up at variance-computation time
rather than stored redundantly on this row.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import Currency
from app.db.base import AuditMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin


class Budget(Base, UUIDPrimaryKeyMixin, TimestampMixin, AuditMixin):
    __tablename__ = "budgets"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_code: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    budgeted_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(String(3), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Budget id={self.id} {self.account_code} "
            f"{self.period_start}..{self.period_end} {self.budgeted_amount}>"
        )
