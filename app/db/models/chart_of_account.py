"""
app.db.models.chart_of_account
=================================
`ChartOfAccount`: the missing piece that turns raw journal entry lines
(`account_code` as a bare string — see `app.services.posting_service`)
into something a financial report can actually classify. Every account
code that `PostingService` writes to (`DefaultAccounts.CASH`,
`ACCOUNTS_PAYABLE`, etc.) must have a corresponding row here before
`FinancialReportingService` can produce a correct Trial Balance, P&L,
or Balance Sheet — reports group and sign accounts by `account_type`
and `is_contra`, not by parsing the account code string.

NORMAL BALANCE (`normal_side` property)
-------------------------------------------
Standard double-entry accounting: Assets and Expenses have a normal
DEBIT balance (increased by debits); Liabilities, Equity, and Revenue
have a normal CREDIT balance (increased by credits). `is_contra` flips
this — e.g. `PURCHASE_RETURNS` (`5100-PURRET`, an EXPENSE account) is a
*contra-expense* account: it reduces net expense, so it carries a
normal CREDIT balance despite being classified as EXPENSE. Getting this
flip wrong silently produces a Balance Sheet or P&L that looks
plausible but is arithmetically backwards for that account — which is
exactly the kind of error that's hard to spot by eye, so it's modeled
as an explicit boolean rather than inferred.

SEEDED ACCOUNTS
------------------
`alembic/versions/0004_chart_of_accounts.py` seeds this table with
every account code `DefaultAccounts` (in `posting_service.py`) already
posts to. Adding a new account code to `DefaultAccounts` without adding
a matching row here will make `FinancialReportingService` raise rather
than silently misclassify — see that service's docstring.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import AccountType


class ChartOfAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chart_of_accounts"

    account_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(String(16), nullable=False)
    is_contra: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, doc="See module docstring on normal-balance flipping."
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def normal_side(self) -> str:
        """Returns 'debit' or 'credit' — which side increases this
        account's balance. Used by FinancialReportingService to sign
        each account's net balance consistently."""
        debit_normal_types = {AccountType.ASSET, AccountType.EXPENSE}
        is_debit_normal = self.account_type in debit_normal_types
        if self.is_contra:
            is_debit_normal = not is_debit_normal
        return "debit" if is_debit_normal else "credit"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChartOfAccount code={self.account_code!r} type={self.account_type}>"
