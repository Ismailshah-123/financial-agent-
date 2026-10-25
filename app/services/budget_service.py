"""
app.services.budget_service
===============================
Deterministic core for budget tracking: given a `Budget`, compares
actual account activity (via `FinancialReportingService._account_balances`,
reused directly rather than duplicated — same choice
`app.services.treasury_service` makes) against the budgeted amount, and
projects whether current spending/earning PACE is on track to breach it
even before the period ends.

WHY PACE, NOT JUST A TOTAL-SO-FAR CHECK
------------------------------------------------
A raw "actual vs budgeted" comparison is only useful once the period is
basically over — at 20% through a quarter, "only $2,000 of a $10,000
budget spent" tells you nothing about whether that's on track or
already alarming. `compute_variance` instead compares actual activity
to `expected_amount_at_pace` (`budgeted_amount * elapsed_fraction`) —
what a perfectly linear spend/earn rate would have produced by `as_of`.
This is what makes the check useful as an EARLY warning, not just a
post-mortem. As `as_of` approaches `period_end`, `elapsed_fraction`
approaches 1.0 and `expected_amount_at_pace` approaches
`budgeted_amount` itself — the pace check naturally tightens into the
traditional "did we go over" check as the period concludes, so there's
deliberately only one variance computation here, not two.

WHY DIRECTION FLIPS BY ACCOUNT TYPE
------------------------------------------------
For an EXPENSE account, spending MORE than the pace-adjusted target is
the bad direction. For a REVENUE account, earning LESS than the
pace-adjusted target is bad — a revenue "budget" is a floor, not a
ceiling. `variance_ratio` below is normalized so POSITIVE always means
"trending unfavorable" regardless of which type of account the budget
is against, so `BudgetPlanningAgent`'s risk tiers don't need to know
which direction is which.

KNOWN LIMITATION: LINEAR PACE ASSUMPTION
------------------------------------------------
Real spending is often lumpy, not linear — an annual software license
paid in month one makes that month look wildly "over pace" against a
smooth 1/12th-per-month expectation even though the full-year budget
is perfectly fine. This is a genuine, un-fixed v1 simplification, not
a hidden one — see `BUDGET_VARIANCE_*_RATIO` below for where to
recalibrate, and `BudgetPlanningAgent`'s docstring for how this
tempers confidence on early-period findings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.db.models.budget import Budget
from app.db.models.enums import AccountType
from app.repositories.budget_repository import BudgetRepository
from app.repositories.chart_of_account_repository import ChartOfAccountRepository
from app.services.financial_reporting_service import FinancialReportingService

# v1 heuristics — same "named constant, not derived from historical
# data, recalibrate later" convention as every other agent's tuning
# constants this session (see FraudDetectionService, TreasuryService).
CRITICAL_VARIANCE_RATIO = Decimal("0.25")  # 25%+ unfavorable vs. pace-adjusted target
HIGH_VARIANCE_RATIO = Decimal("0.10")  # 10-25% unfavorable

# Account types a "budget" meaningfully applies to, and which direction
# is unfavorable for each. Other account types (ASSET/LIABILITY/EQUITY)
# aren't rejected outright — a budget against them just always reports
# zero variance risk, since neither "spending" nor "earning" framing
# fits — see BudgetService.compute_variance.
_UNFAVORABLE_DIRECTION = {
    AccountType.EXPENSE.value: "over",  # actual > expected is bad
    AccountType.REVENUE.value: "under",  # actual < expected is bad
}


@dataclass(frozen=True)
class BudgetVariance:
    budget: Budget
    account_type: str
    actual_amount: Decimal
    elapsed_fraction: Decimal  # 0.0-1.0 (clamped) — how far through the period `as_of` is
    expected_amount_at_pace: Decimal
    variance_ratio: Decimal  # positive = trending unfavorable, regardless of account type
    is_meaningful: bool  # False for account types a budget doesn't meaningfully constrain


class BudgetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.budget_repository = BudgetRepository(session)
        self.chart_of_account_repository = ChartOfAccountRepository(session)
        self.reporting_service = FinancialReportingService(session)

    async def create_budget(
        self,
        *,
        name: str,
        account_code: str,
        period_start: date,
        period_end: date,
        budgeted_amount: Decimal,
        currency,
        notes: str | None,
        actor_id: str,
    ) -> Budget:
        if period_start > period_end:
            raise ValidationError(
                f"period_start ({period_start}) must not be after period_end ({period_end})."
            )
        if budgeted_amount <= 0:
            raise ValidationError(f"budgeted_amount must be positive, got {budgeted_amount}.")

        account = await self.chart_of_account_repository.get_by_code(account_code)
        if account is None:
            raise ValidationError(
                f"account_code '{account_code}' is not in the chart of accounts."
            )

        overlapping = await self.budget_repository.list_overlapping(
            account_code=account_code, period_start=period_start, period_end=period_end
        )
        if overlapping:
            conflict = overlapping[0]
            raise ValidationError(
                f"A budget for '{account_code}' already covers an overlapping period "
                f"({conflict.period_start} to {conflict.period_end}, id={conflict.id}).",
                details={"conflicting_budget_id": str(conflict.id)},
            )

        budget = Budget(
            name=name,
            account_code=account_code,
            period_start=period_start,
            period_end=period_end,
            budgeted_amount=budgeted_amount,
            currency=currency,
            notes=notes,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        return await self.budget_repository.add(budget)

    async def compute_variance(self, budget: Budget, *, as_of: date) -> BudgetVariance:
        account = await self.chart_of_account_repository.get_by_code(budget.account_code)
        if account is None:  # pragma: no cover — defensive; create_budget already validated this
            raise NotFoundError(f"Account '{budget.account_code}' not found.")

        balances = await self.reporting_service._account_balances(
            start_date=budget.period_start, end_date=min(as_of, budget.period_end)
        )
        actual_amount = next(
            (b.balance for b in balances if b.account_code == budget.account_code),
            Decimal("0"),
        )

        elapsed_fraction = _elapsed_fraction(
            as_of=as_of, period_start=budget.period_start, period_end=budget.period_end
        )
        expected_amount_at_pace = (budget.budgeted_amount * elapsed_fraction).quantize(
            Decimal("0.01")
        )

        direction = _UNFAVORABLE_DIRECTION.get(account.account_type)
        if direction is None or budget.budgeted_amount == 0:
            return BudgetVariance(
                budget=budget,
                account_type=account.account_type,
                actual_amount=actual_amount,
                elapsed_fraction=elapsed_fraction,
                expected_amount_at_pace=expected_amount_at_pace,
                variance_ratio=Decimal("0"),
                is_meaningful=False,
            )

        raw_variance = (
            actual_amount - expected_amount_at_pace
            if direction == "over"
            else expected_amount_at_pace - actual_amount
        )
        variance_ratio = raw_variance / budget.budgeted_amount

        return BudgetVariance(
            budget=budget,
            account_type=account.account_type,
            actual_amount=actual_amount,
            elapsed_fraction=elapsed_fraction,
            expected_amount_at_pace=expected_amount_at_pace,
            variance_ratio=variance_ratio,
            is_meaningful=True,
        )


def assess_variance_risk(variance: BudgetVariance) -> str:
    """Pure. 'low' | 'medium' | 'high' | 'critical'."""
    if not variance.is_meaningful or variance.variance_ratio <= 0:
        return "low"
    if variance.variance_ratio >= CRITICAL_VARIANCE_RATIO:
        return "critical"
    if variance.variance_ratio >= HIGH_VARIANCE_RATIO:
        return "high"
    return "medium"


def _elapsed_fraction(*, as_of: date, period_start: date, period_end: date) -> Decimal:
    """Pure. 0.0 if as_of is before the period starts, 1.0 if at/after
    it ends, otherwise the fraction of the period elapsed."""
    total_days = (period_end - period_start).days
    if total_days <= 0:
        return Decimal("1")  # zero/negative-length period — treat as fully elapsed
    elapsed_days = (as_of - period_start).days
    if elapsed_days <= 0:
        return Decimal("0")
    if elapsed_days >= total_days:
        return Decimal("1")
    return (Decimal(elapsed_days) / Decimal(total_days)).quantize(Decimal("0.0001"))


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
