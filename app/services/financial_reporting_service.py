"""
app.services.financial_reporting_service
===========================================
Turns posted journal entries into the three foundational financial
reports: Trial Balance, Profit & Loss (Income Statement), and Balance
Sheet. This is the first thing in the codebase that actually *reads*
the ledger `PostingService` has been writing to since Phase 1 — every
other service only ever wrote journal entries, never aggregated them.

ARCHITECTURE: DB AGGREGATION, THEN PURE CALCULATION
--------------------------------------------------------
`_aggregate_by_account` is the only DB-touching piece (a grouped SUM
query). Everything downstream of it — `compute_account_balance` and the
report-assembly logic — is plain, DB-free Python operating on the
aggregated numbers, which is what makes `compute_account_balance`
directly unit-testable (tests/unit/test_financial_reporting_service.py)
without a database at all.

INVARIANT: EVERY POSTED ACCOUNT MUST BE IN THE CHART OF ACCOUNTS
----------------------------------------------------------------------
If a journal entry line references an `account_code` with no matching
`ChartOfAccount` row, this service raises `ValidationError` naming the
code — it does NOT silently drop that account from the report. A
financial report that's silently missing an account is far more
dangerous than one that refuses to generate at all, since the person
reading it has no way to know something is missing.

CURRENCY POLICY — NO IMPLICIT CROSS-CURRENCY ARITHMETIC
-----------------------------------------------------------
Every `JournalEntry` carries one currency and the platform has no
authoritative FX-rate model. Reports are therefore produced for ONE
currency at a time: lines are filtered to `JournalEntry.currency ==
<currency>` before any summation, and the chosen currency is returned on
the report. If the caller omits `currency` and the reporting window holds
posted entries in more than one currency, `resolve_report_currency`
raises `ValidationError` listing the available currencies instead of
adding unlike amounts together. No exchange rate is invented or applied.

LIMITATION — READ BEFORE TREATING THE BALANCE SHEET AS AUTHORITATIVE
--------------------------------------------------------------------------
The Balance Sheet's equity section is a single computed "Retained
Earnings" line: cumulative (Revenue - Expense) across every posted
journal entry from inception through `as_of`. This platform doesn't
model a period-close process (a real close posts net income INTO an
actual Retained Earnings equity account via closing entries) — so this
number is directionally correct but is a live computation, not a
posted balance. Any `ChartOfAccount` rows explicitly typed `EQUITY`
(there are none seeded by default) are added on top of this computed
figure. Treat this report as management-reporting quality, not
audit/close-ready, until a real closing-entry process exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.db.models.chart_of_account import ChartOfAccount
from app.db.models.enums import AccountType, JournalEntryStatus
from app.db.models.journal_entry import JournalEntry, JournalEntryLine
from app.repositories.chart_of_account_repository import ChartOfAccountRepository
from app.services.report_currency import resolve_report_currency


@dataclass
class AccountBalance:
    account_code: str
    account_name: str
    account_type: AccountType
    total_debit: Decimal
    total_credit: Decimal
    balance: Decimal  # signed per the account's normal side


@dataclass
class TrialBalanceReport:
    as_of: date
    lines: list[AccountBalance] = field(default_factory=list)
    total_debit: Decimal = Decimal("0")
    total_credit: Decimal = Decimal("0")
    is_balanced: bool = True
    currency: str | None = None
    available_currencies: list[str] = field(default_factory=list)


@dataclass
class ProfitAndLossReport:
    start_date: date
    end_date: date
    revenue_lines: list[AccountBalance] = field(default_factory=list)
    expense_lines: list[AccountBalance] = field(default_factory=list)
    total_revenue: Decimal = Decimal("0")
    total_expense: Decimal = Decimal("0")
    net_income: Decimal = Decimal("0")
    currency: str | None = None
    available_currencies: list[str] = field(default_factory=list)


@dataclass
class BalanceSheetReport:
    as_of: date
    asset_lines: list[AccountBalance] = field(default_factory=list)
    liability_lines: list[AccountBalance] = field(default_factory=list)
    equity_lines: list[AccountBalance] = field(default_factory=list)
    total_assets: Decimal = Decimal("0")
    total_liabilities: Decimal = Decimal("0")
    total_equity: Decimal = Decimal("0")
    computed_retained_earnings: Decimal = Decimal("0")
    is_balanced: bool = True
    currency: str | None = None
    available_currencies: list[str] = field(default_factory=list)


def compute_account_balance(
    *, total_debit: Decimal, total_credit: Decimal, normal_side: str
) -> Decimal:
    """Pure. `normal_side` is 'debit' or 'credit'
    (`ChartOfAccount.normal_side`). A debit-normal account's balance is
    debit-minus-credit; a credit-normal account's is credit-minus-debit
    — this is what makes every account's balance a "how much of its
    normal side does it have" number, positive when healthy, negative
    when something's off (e.g. a debit-normal Cash account showing a
    negative balance means more credited out than ever debited in)."""
    if normal_side == "debit":
        return total_debit - total_credit
    return total_credit - total_debit


class FinancialReportingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.chart_of_account_repository = ChartOfAccountRepository(session)

    async def list_posted_currencies(self) -> list[str]:
        """Distinct currencies with at least one posted journal entry."""
        return await self._posted_currencies(start_date=None, end_date=None)

    async def trial_balance(
        self, *, as_of: date, currency: str | None = None
    ) -> TrialBalanceReport:
        available = await self._posted_currencies(start_date=None, end_date=as_of)
        selected = resolve_report_currency(available, currency)
        balances = await self._account_balances(
            start_date=None, end_date=as_of, currency=selected
        )
        total_debit = sum((b.total_debit for b in balances), Decimal("0"))
        total_credit = sum((b.total_credit for b in balances), Decimal("0"))
        return TrialBalanceReport(
            as_of=as_of,
            lines=sorted(balances, key=lambda b: b.account_code),
            total_debit=total_debit,
            total_credit=total_credit,
            is_balanced=(total_debit == total_credit),
            currency=selected,
            available_currencies=available,
        )

    async def profit_and_loss(
        self, *, start_date: date, end_date: date, currency: str | None = None
    ) -> ProfitAndLossReport:
        available = await self._posted_currencies(start_date=start_date, end_date=end_date)
        selected = resolve_report_currency(available, currency)
        balances = await self._account_balances(
            start_date=start_date, end_date=end_date, currency=selected
        )
        revenue_lines = sorted(
            (b for b in balances if b.account_type == AccountType.REVENUE),
            key=lambda b: b.account_code,
        )
        expense_lines = sorted(
            (b for b in balances if b.account_type == AccountType.EXPENSE),
            key=lambda b: b.account_code,
        )
        total_revenue = sum((b.balance for b in revenue_lines), Decimal("0"))
        total_expense = sum((b.balance for b in expense_lines), Decimal("0"))
        return ProfitAndLossReport(
            start_date=start_date,
            end_date=end_date,
            revenue_lines=revenue_lines,
            expense_lines=expense_lines,
            total_revenue=total_revenue,
            total_expense=total_expense,
            net_income=total_revenue - total_expense,
            currency=selected,
            available_currencies=available,
        )

    async def balance_sheet(
        self, *, as_of: date, currency: str | None = None
    ) -> BalanceSheetReport:
        available = await self._posted_currencies(start_date=None, end_date=as_of)
        selected = resolve_report_currency(available, currency)
        balances = await self._account_balances(
            start_date=None, end_date=as_of, currency=selected
        )
        asset_lines = sorted(
            (b for b in balances if b.account_type == AccountType.ASSET),
            key=lambda b: b.account_code,
        )
        liability_lines = sorted(
            (b for b in balances if b.account_type == AccountType.LIABILITY),
            key=lambda b: b.account_code,
        )
        equity_lines = sorted(
            (b for b in balances if b.account_type == AccountType.EQUITY),
            key=lambda b: b.account_code,
        )

        total_assets = sum((b.balance for b in asset_lines), Decimal("0"))
        total_liabilities = sum((b.balance for b in liability_lines), Decimal("0"))
        explicit_equity = sum((b.balance for b in equity_lines), Decimal("0"))

        # Cumulative net income since inception — see module docstring's
        # "computed, not closed" limitation.
        total_revenue = sum(
            (b.balance for b in balances if b.account_type == AccountType.REVENUE),
            Decimal("0"),
        )
        total_expense = sum(
            (b.balance for b in balances if b.account_type == AccountType.EXPENSE),
            Decimal("0"),
        )
        computed_retained_earnings = total_revenue - total_expense
        total_equity = explicit_equity + computed_retained_earnings

        return BalanceSheetReport(
            as_of=as_of,
            asset_lines=asset_lines,
            liability_lines=liability_lines,
            equity_lines=equity_lines,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            total_equity=total_equity,
            computed_retained_earnings=computed_retained_earnings,
            is_balanced=(total_assets == total_liabilities + total_equity),
            currency=selected,
            available_currencies=available,
        )

    # ------------------------------------------------------------------
    # Internal: DB aggregation + chart-of-accounts classification
    # ------------------------------------------------------------------
    async def _posted_currencies(
        self, *, start_date: date | None, end_date: date | None
    ) -> list[str]:
        stmt = (
            select(JournalEntry.currency)
            .where(JournalEntry.status == JournalEntryStatus.POSTED.value)
            .distinct()
        )
        if start_date is not None:
            stmt = stmt.where(JournalEntry.posting_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(JournalEntry.posting_date <= end_date)
        result = await self.session.execute(stmt)
        return sorted({str(row[0]).strip().upper() for row in result.all() if row[0]})

    async def _aggregate_by_account(
        self, *, start_date: date | None, end_date: date, currency: str | None
    ) -> dict[str, tuple[Decimal, Decimal]]:
        if currency is None:
            # Nothing is posted in the window, so there is nothing to sum.
            return {}
        stmt = (
            select(
                JournalEntryLine.account_code,
                func.coalesce(func.sum(JournalEntryLine.debit), 0),
                func.coalesce(func.sum(JournalEntryLine.credit), 0),
            )
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .where(JournalEntry.status == JournalEntryStatus.POSTED.value)
            .where(JournalEntry.currency == currency)
            .where(JournalEntry.posting_date <= end_date)
            .group_by(JournalEntryLine.account_code)
        )
        if start_date is not None:
            stmt = stmt.where(JournalEntry.posting_date >= start_date)

        result = await self.session.execute(stmt)
        return {row[0]: (Decimal(row[1]), Decimal(row[2])) for row in result.all()}

    async def _account_balances(
        self, *, start_date: date | None, end_date: date, currency: str | None
    ) -> list[AccountBalance]:
        raw = await self._aggregate_by_account(
            start_date=start_date, end_date=end_date, currency=currency
        )
        balances: list[AccountBalance] = []
        for account_code, (total_debit, total_credit) in raw.items():
            account = await self.chart_of_account_repository.get_by_code(account_code)
            if account is None:
                raise ValidationError(
                    f"Journal entries reference account code '{account_code}', which "
                    f"has no entry in the chart of accounts. Add it before generating "
                    f"reports — see app.db.models.chart_of_account.",
                    details={"account_code": account_code},
                )
            balances.append(self._to_account_balance(account, total_debit, total_credit))
        return balances

    @staticmethod
    def _to_account_balance(
        account: ChartOfAccount, total_debit: Decimal, total_credit: Decimal
    ) -> AccountBalance:
        balance = compute_account_balance(
            total_debit=total_debit, total_credit=total_credit, normal_side=account.normal_side
        )
        return AccountBalance(
            account_code=account.account_code,
            account_name=account.account_name,
            account_type=AccountType(account.account_type),
            total_debit=total_debit,
            total_credit=total_credit,
            balance=balance,
        )
