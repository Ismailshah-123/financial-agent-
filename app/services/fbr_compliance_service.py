"""
app.services.fbr_compliance_service
=======================================
Deterministic core for FBR withholding-tax remittance compliance:
compares the withholding tax liability INCURRED in a period (from
`DefaultAccounts.WITHHOLDING_TAX_PAYABLE` account activity — reusing
`FinancialReportingService._account_balances` directly, same choice
`TreasuryService`/`BudgetService` make) against what's actually been
RECORDED as remitted to FBR (`FBRRemittance` rows) for that period.

SCOPE: WITHHOLDING TAX ONLY, NOT GST/SALES TAX
------------------------------------------------------
This platform's tax model has two mechanisms (see
`app.db.models.enums.TaxType`'s docstring): SALES_TAX, added on top of
an invoice and owed to the customer relationship, vs. WITHHOLDING_TAX,
deducted FROM a payment and owed directly to FBR. Only the latter has
a liability account (2100-WHT) and a payment-execution-time posting
this platform tracks — sales tax collected doesn't accumulate in a
comparable liability account anywhere yet. Remittance compliance
checking is therefore scoped to withholding tax only; GST/sales tax
remittance tracking would need its own liability account and its own
filing cadence this v1 doesn't model. Documented here rather than
silently only covering part of what "FBR compliance" might suggest.

ILLUSTRATIVE GRACE PERIOD, NOT VERIFIED-CURRENT FBR LAW
------------------------------------------------------------------
`REMITTANCE_GRACE_DAYS` is a placeholder assumption about how long
after a period ends a remittance is expected, in the same spirit as
every other Pakistan-tax-specific number in this codebase (see
`alembic/versions/0005_tax_codes.py`'s seeded rates) — illustrative,
not verified against current FBR notifications. Confirm the real
filing deadline before this assessment's timing judgment (not the
underlying liability math, which is exact) is relied on for real
compliance decisions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.db.models.fbr_remittance import FBRRemittance
from app.repositories.fbr_remittance_repository import FBRRemittanceRepository
from app.services.financial_reporting_service import FinancialReportingService
from app.services.posting_service import DefaultAccounts

# v1 heuristic — see module docstring's caveat above.
REMITTANCE_GRACE_DAYS = 15

CRITICAL_OVERDUE_DAYS = REMITTANCE_GRACE_DAYS * 2


@dataclass(frozen=True)
class RemittanceAssessment:
    period_start: date
    period_end: date
    as_of: date
    liability_incurred: Decimal
    amount_remitted: Decimal
    outstanding_amount: Decimal
    days_since_period_end: int


class FBRComplianceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.remittance_repository = FBRRemittanceRepository(session)
        self.reporting_service = FinancialReportingService(session)

    async def record_remittance(
        self,
        *,
        period_start: date,
        period_end: date,
        amount_remitted: Decimal,
        currency,
        remitted_date: date,
        fbr_reference: str,
        notes: str | None,
        actor_id: str,
    ) -> FBRRemittance:
        if period_start > period_end:
            raise ValidationError(
                f"period_start ({period_start}) must not be after period_end ({period_end})."
            )
        if amount_remitted <= 0:
            raise ValidationError(f"amount_remitted must be positive, got {amount_remitted}.")

        remittance = FBRRemittance(
            period_start=period_start,
            period_end=period_end,
            amount_remitted=amount_remitted,
            currency=currency,
            remitted_date=remitted_date,
            fbr_reference=fbr_reference,
            notes=notes,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        return await self.remittance_repository.add(remittance)

    async def assess_remittance(
        self, *, period_start: date, period_end: date, as_of: date
    ) -> RemittanceAssessment:
        if period_start > period_end:
            raise ValidationError(
                f"period_start ({period_start}) must not be after period_end ({period_end})."
            )

        balances = await self.reporting_service._account_balances(
            start_date=period_start, end_date=period_end
        )
        liability_incurred = next(
            (
                b.balance
                for b in balances
                if b.account_code == DefaultAccounts.WITHHOLDING_TAX_PAYABLE
            ),
            Decimal("0"),
        )

        remittances = await self.remittance_repository.list_overlapping(
            period_start=period_start, period_end=period_end
        )
        amount_remitted = sum((r.amount_remitted for r in remittances), Decimal("0"))

        outstanding_amount = liability_incurred - amount_remitted
        days_since_period_end = (as_of - period_end).days

        return RemittanceAssessment(
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
            liability_incurred=liability_incurred,
            amount_remitted=amount_remitted,
            outstanding_amount=outstanding_amount,
            days_since_period_end=days_since_period_end,
        )


def assess_compliance_risk(assessment: RemittanceAssessment) -> str:
    """Pure. 'low' | 'medium' | 'high' | 'critical'."""
    if assessment.outstanding_amount <= 0:
        return "low"
    if assessment.days_since_period_end <= REMITTANCE_GRACE_DAYS:
        return "medium"  # outstanding, but not yet past the (illustrative) deadline
    if assessment.days_since_period_end <= CRITICAL_OVERDUE_DAYS:
        return "high"
    return "critical"


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
