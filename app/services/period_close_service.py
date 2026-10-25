"""
app.services.period_close_service
=====================================
Closes the gap `FinancialReportingService`'s module docstring flags:
posts real closing journal entries that zero out Revenue/Expense
accounts into `DefaultAccounts.RETAINED_EARNINGS` (3000-RE), for a
given [start_date, end_date] range.

WHY THIS DOESN'T ALSO NEED TO CHANGE FinancialReportingService
--------------------------------------------------------------------------
This is worth spelling out because it isn't obvious: once real closing
entries exist, `FinancialReportingService.balance_sheet`'s existing
"cumulative revenue/expense since inception" computation — unchanged —
automatically nets down to just the CURRENT, not-yet-closed period.
A closing entry debits Revenue by its period balance and credits
Expense by its period balance; querying "cumulative since inception"
afterward sums the original postings AND the closing entry's opposite-
signed lines for that same period, which cancel to zero for any
already-closed range. Only activity dated after the last close's
end_date survives the cancellation. Meanwhile 3000-RE, now a real
EQUITY account, accumulates each close's net income independently and
shows up in `equity_lines` like any other posted account. The two
pieces (real RE + live current-period computation) sum to exactly what
the old single "cumulative since inception" number represented — this
service makes that number honest by construction, not by changing how
it's calculated.

ONE IMPLICATION WORTH KNOWING: a Profit & Loss report for a date range
that SPANS an already-closed sub-range will show that sub-range's
revenue/expense as zero (correctly reflecting the ledger, which has
been netted out by the closing entry) — not the period's real
activity. That real activity is exactly what this service snapshots
onto the `PeriodClose` row (`total_revenue`/`total_expense`/
`net_income`) at close time. Once a period is closed, its P&L lives on
that row, not in a live report query spanning the closed range.

VALIDATION RULES
-----------------
- `start_date <= end_date`.
- `end_date` cannot be in the future — a period can only be closed once
  it's actually over.
- No overlap with any existing, still-in-effect (not reopened) close.
- `start_date` must be after the latest existing close's `end_date` —
  periods close in order. This does NOT require zero-gap adjacency
  (e.g. skipping straight to closing Q3 without ever closing Q1/Q2 is
  allowed) — only that you can't close backward over something already
  closed.
- The period must have SOME revenue or expense activity — closing an
  empty period is almost certainly a date-range mistake, not a real
  close.

REOPENING
---------
`reopen_period` never edits or deletes the original closing entry —
immutable ledger, same principle as everywhere else in this codebase.
It posts a new REVERSING entry (every line's debit/credit swapped,
dated TODAY — a currently-open date, deliberately not back-dated into
the period being reopened) and marks the `PeriodClose` row. The period
is open again for new postings the moment this entry lands, because
`PostingService.post`'s lock check only looks at NOT-reopened closes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Currency, TransactionType
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.db.models.period_close import PeriodClose
from app.repositories.period_close_repository import PeriodCloseRepository
from app.services.financial_reporting_service import FinancialReportingService
from app.services.posting_service import DefaultAccounts, PostingLine, PostingService

logger = get_logger(__name__)


class PeriodCloseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.period_close_repository = PeriodCloseRepository(session)
        self.reporting_service = FinancialReportingService(session)
        self.posting_service = PostingService(session)

    async def close_period(
        self,
        *,
        start_date: date,
        end_date: date,
        actor_id: str,
        currency: Currency = Currency.PKR,
    ) -> PeriodClose:
        await self._validate_close_request(start_date=start_date, end_date=end_date)

        pnl = await self.reporting_service.profit_and_loss(
            start_date=start_date, end_date=end_date
        )
        if pnl.total_revenue == 0 and pnl.total_expense == 0:
            raise ValidationError(
                f"No revenue or expense activity between {start_date} and "
                f"{end_date} — nothing to close. This usually means the date "
                f"range is wrong.",
                details={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
            )

        lines: list[PostingLine] = []
        for line in pnl.revenue_lines:
            if line.balance != 0:
                lines.append(
                    PostingLine(
                        account_code=line.account_code,
                        debit=line.balance,
                        description=f"Period close {start_date}\u2013{end_date}: zero out revenue",
                    )
                )
        for line in pnl.expense_lines:
            if line.balance != 0:
                lines.append(
                    PostingLine(
                        account_code=line.account_code,
                        credit=line.balance,
                        description=f"Period close {start_date}\u2013{end_date}: zero out expense",
                    )
                )

        net_income = pnl.net_income
        if net_income >= 0:
            lines.append(
                PostingLine(
                    account_code=DefaultAccounts.RETAINED_EARNINGS,
                    credit=net_income,
                    description=f"Period close {start_date}\u2013{end_date}: net income to retained earnings",
                )
            )
        else:
            lines.append(
                PostingLine(
                    account_code=DefaultAccounts.RETAINED_EARNINGS,
                    debit=abs(net_income),
                    description=f"Period close {start_date}\u2013{end_date}: net loss to retained earnings",
                )
            )

        # Generated up front so the closing journal entry's reference_id
        # can point at this PeriodClose row before the row itself is
        # persisted — see module docstring's polymorphic reference_id
        # convention in journal_entry.py.
        period_close_id = uuid.uuid4()
        journal_entry = await self.posting_service.post(
            transaction_type=TransactionType.PERIOD_CLOSE,
            reference_id=period_close_id,
            posting_date=end_date,
            currency=currency,
            lines=lines,
            actor_id=actor_id,
        )

        period_close = PeriodClose(
            id=period_close_id,
            start_date=start_date,
            end_date=end_date,
            closing_journal_entry_id=journal_entry.id,
            total_revenue=pnl.total_revenue,
            total_expense=pnl.total_expense,
            net_income=net_income,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        period_close = await self.period_close_repository.add(period_close)

        logger.info(
            "period_closed",
            period_close_id=str(period_close.id),
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            net_income=str(net_income),
            journal_entry_id=str(journal_entry.id),
        )
        return period_close

    async def reopen_period(
        self, *, period_close_id: uuid.UUID, reason: str, actor_id: str
    ) -> PeriodClose:
        period_close = await self.period_close_repository.get_by_id(period_close_id)
        if period_close is None:
            raise NotFoundError(
                f"PeriodClose with id {period_close_id} not found.",
                details={"model": "PeriodClose", "id": str(period_close_id)},
            )
        if period_close.is_reopened:
            raise ConflictError(
                f"Period {period_close.start_date} to {period_close.end_date} is "
                f"already reopened (since {period_close.reopened_at}).",
                details={"period_close_id": str(period_close_id)},
            )

        original_entry = await self.posting_service.repository.get_by_id_with_lines(
            period_close.closing_journal_entry_id
        )
        if original_entry is None:  # pragma: no cover — defensive; FK guarantees this
            raise NotFoundError(
                "The original closing journal entry is missing — cannot safely reopen.",
                details={"journal_entry_id": str(period_close.closing_journal_entry_id)},
            )

        reversing_lines = [
            PostingLine(
                account_code=original_line.account_code,
                debit=original_line.credit,
                credit=original_line.debit,
                description=(
                    f"Reversal of period close {period_close.start_date}"
                    f"\u2013{period_close.end_date}: {reason}"
                ),
            )
            for original_line in original_entry.lines
        ]
        reversing_entry = await self.posting_service.post(
            transaction_type=TransactionType.PERIOD_CLOSE,
            reference_id=period_close.id,
            posting_date=date.today(),
            currency=Currency(original_entry.currency),
            lines=reversing_lines,
            actor_id=actor_id,
        )

        period_close.is_reopened = True
        period_close.reopened_at = datetime.now(timezone.utc)
        period_close.reopened_by_id = uuid.UUID(actor_id) if _is_uuid(actor_id) else None
        period_close.reopen_reason = reason
        period_close.reopening_journal_entry_id = reversing_entry.id
        await self.session.flush()

        logger.info(
            "period_reopened",
            period_close_id=str(period_close.id),
            reversing_journal_entry_id=str(reversing_entry.id),
            reason=reason,
        )
        return period_close

    # ------------------------------------------------------------------
    async def _validate_close_request(self, *, start_date: date, end_date: date) -> None:
        if start_date > end_date:
            raise ValidationError(
                f"start_date ({start_date}) must not be after end_date ({end_date})."
            )
        if end_date > date.today():
            raise ValidationError(
                f"Cannot close a period ending in the future ({end_date}); "
                f"today is {date.today()}."
            )

        overlapping = await self.period_close_repository.list_overlapping(
            start_date=start_date, end_date=end_date
        )
        if overlapping:
            conflict = overlapping[0]
            raise ConflictError(
                f"Requested range {start_date} to {end_date} overlaps the "
                f"already-closed period {conflict.start_date} to "
                f"{conflict.end_date}.",
                details={"conflicting_period_close_id": str(conflict.id)},
            )

        latest = await self.period_close_repository.get_latest_close()
        if latest is not None and start_date <= latest.end_date:
            raise ConflictError(
                f"Periods must close in order: the latest closed period ends "
                f"{latest.end_date}, so start_date must be after that "
                f"(requested start_date was {start_date}).",
                details={"latest_period_close_id": str(latest.id)},
            )


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
