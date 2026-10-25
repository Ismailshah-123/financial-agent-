"""
app.services.fraud_detection_service
========================================
Deterministic core for payment fraud screening: given one
`OutgoingPayment`, checks it and its `Vendor` against a fixed set of
rule-based signals. See `app.agents.fraud_detection.agent` for how
these combine into a risk-leveled `AgentDecision`, and why the LLM in
that agent is used only to narrate these findings, never to decide
them — every signal below is a plain, auditable, deterministic rule.
`FraudDetectionAgent`'s risk-level assignment never depends on
anything an LLM call could fail to produce.

WHAT EACH SIGNAL CAN AND CAN'T TELL YOU
------------------------------------------------
- **Vendor status** (BLOCKED/PENDING_REVIEW/INACTIVE): the strongest
  signal here — a payment to a vendor that hasn't cleared onboarding
  review, or has been explicitly blocked, is a process violation on its
  own regardless of anything else about the payment.
- **Recently modified vendor record**: `Vendor.updated_at` differing
  from `created_at` and falling shortly before the payment date. This
  is deliberately described as "the vendor record was modified", NOT
  "bank details were changed" — there is no field-level change history
  on `Vendor` (see that model's docstring), so this signal can't tell
  you WHAT changed, only THAT something did. `VendorService`'s module
  docstring names exactly this fraud pattern (a vendor "emailing in a
  new IBAN") as the priority use case a proper audit-log table would
  serve; until one exists, this coarser signal is what's available, and
  is presented as a prompt to verify recent changes through a separate
  channel, not as confirmation that banking details specifically moved.
- **New vendor + large/first payment, near-approval-limit amounts,
  duplicate payments**: all directly computable from existing fields
  (`Vendor.created_at`, `Vendor.approval_limit`, `OutgoingPayment`
  history) with no such caveat.

NONE OF THESE SIGNALS PROVE FRAUD
------------------------------------------
Every one of them also fires for entirely legitimate activity (a
vendor's address gets corrected; a new supplier's first order happens
to be large). That's why this service returns signals with severities
for a human to weigh, not a fraud/not-fraud verdict — same "AI never
transacts without approval" rule as everywhere else in this platform,
arguably more important here than anywhere else in it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import VendorStatus
from app.db.models.payment import OutgoingPayment
from app.db.models.vendor import Vendor
from app.repositories.payment_repository import PaymentRepository
from app.repositories.vendor_repository import VendorRepository

# Tuning constants — v1 heuristics, not derived from any historical
# fraud-loss analysis (none exists yet for this platform). Each is
# named so a future recalibration has an obvious place to change it.
RECENTLY_MODIFIED_WINDOW_DAYS = 7
NEW_VENDOR_WINDOW_DAYS = 30
NEAR_APPROVAL_LIMIT_THRESHOLD = Decimal("0.90")  # 90% of the limit or more
DUPLICATE_PAYMENT_WINDOW_DAYS = 7

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class FraudSignal:
    signal_type: str
    severity: str  # "low" | "medium" | "high" | "critical"
    description: str


class FraudDetectionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.payment_repository = PaymentRepository(session)
        self.vendor_repository = VendorRepository(session)

    async def detect_signals(
        self, *, payment: OutgoingPayment, vendor: Vendor
    ) -> list[FraudSignal]:
        signals: list[FraudSignal] = []

        status_signal = self._check_vendor_status(vendor)
        if status_signal is not None:
            signals.append(status_signal)

        payment_date = payment.executed_date or payment.scheduled_date

        modified_signal = self._check_recently_modified(vendor, payment_date)
        if modified_signal is not None:
            signals.append(modified_signal)

        new_vendor_signal = self._check_new_vendor_large_payment(
            vendor, payment.amount, payment_date
        )
        if new_vendor_signal is not None:
            signals.append(new_vendor_signal)

        near_limit_signal = self._check_near_approval_limit(vendor, payment.amount)
        if near_limit_signal is not None:
            signals.append(near_limit_signal)

        duplicates = await self.payment_repository.list_other_executed_payments_same_vendor_and_amount(
            vendor_id=vendor.id,
            amount=payment.amount,
            around_date=payment_date,
            exclude_payment_id=payment.id,
            window_days=DUPLICATE_PAYMENT_WINDOW_DAYS,
        )
        if duplicates:
            signals.append(
                FraudSignal(
                    signal_type="duplicate_payment",
                    severity="high",
                    description=(
                        f"{len(duplicates)} other executed payment(s) to this vendor for "
                        f"the exact same amount ({payment.amount}) within "
                        f"{DUPLICATE_PAYMENT_WINDOW_DAYS} days: "
                        f"{', '.join(str(p.id) for p in duplicates)}."
                    ),
                )
            )

        return signals

    # ------------------------------------------------------------------
    def _check_vendor_status(self, vendor: Vendor) -> FraudSignal | None:
        if vendor.status == VendorStatus.BLOCKED.value:
            return FraudSignal(
                signal_type="vendor_blocked",
                severity="critical",
                description=(
                    f"Vendor status is BLOCKED — a payment to a blocked vendor should "
                    f"not proceed without explicit compliance override."
                ),
            )
        if vendor.status == VendorStatus.PENDING_REVIEW.value:
            return FraudSignal(
                signal_type="vendor_pending_review",
                severity="high",
                description=(
                    "Vendor is still PENDING_REVIEW — has not cleared onboarding review, "
                    "yet a payment is being made."
                ),
            )
        if vendor.status == VendorStatus.INACTIVE.value:
            return FraudSignal(
                signal_type="vendor_inactive",
                severity="high",
                description="Vendor is marked INACTIVE, yet a payment is being made.",
            )
        return None

    def _check_recently_modified(
        self, vendor: Vendor, payment_date: date
    ) -> FraudSignal | None:
        if vendor.updated_at is None or vendor.created_at is None:
            return None
        if vendor.updated_at == vendor.created_at:
            return None  # never edited since creation
        days_before_payment = (payment_date - vendor.updated_at.date()).days
        if 0 <= days_before_payment <= RECENTLY_MODIFIED_WINDOW_DAYS:
            return FraudSignal(
                signal_type="vendor_recently_modified",
                severity="medium",
                description=(
                    f"Vendor record was modified {days_before_payment} day(s) before this "
                    f"payment. This platform doesn't track which field changed — if this "
                    f"touched banking details, verify the change through a channel other "
                    f"than the invoice or email requesting it before releasing funds."
                ),
            )
        return None

    def _check_new_vendor_large_payment(
        self, vendor: Vendor, payment_amount: Decimal, payment_date: date
    ) -> FraudSignal | None:
        if vendor.created_at is None:
            return None
        vendor_age_days = (payment_date - vendor.created_at.date()).days
        if vendor_age_days > NEW_VENDOR_WINDOW_DAYS or vendor_age_days < 0:
            return None

        if vendor.approval_limit is not None and payment_amount > vendor.approval_limit:
            return FraudSignal(
                signal_type="new_vendor_exceeds_own_limit",
                severity="high",
                description=(
                    f"Vendor was created {vendor_age_days} day(s) ago, and this payment "
                    f"({payment_amount}) exceeds the vendor's own configured approval_limit "
                    f"({vendor.approval_limit})."
                ),
            )
        return FraudSignal(
            signal_type="new_vendor_payment",
            severity="medium",
            description=(
                f"Vendor was created only {vendor_age_days} day(s) ago — this is an early "
                f"payment in a new vendor relationship, worth a closer look than a "
                f"long-established one."
            ),
        )

    def _check_near_approval_limit(
        self, vendor: Vendor, payment_amount: Decimal
    ) -> FraudSignal | None:
        if vendor.approval_limit is None or vendor.approval_limit <= 0:
            return None
        ratio = payment_amount / vendor.approval_limit
        if NEAR_APPROVAL_LIMIT_THRESHOLD <= ratio < Decimal("1.0"):
            return FraudSignal(
                signal_type="near_approval_limit",
                severity="medium",
                description=(
                    f"Payment ({payment_amount}) is {ratio * 100:.0f}% of the vendor's "
                    f"approval_limit ({vendor.approval_limit}) — close enough below the "
                    f"limit to be worth checking this isn't one purchase split into "
                    f"multiple payments to stay under it."
                ),
            )
        return None


def overall_severity(signals: list[FraudSignal]) -> str:
    """Pure. The highest severity among the given signals, or 'low' if
    there are none — matches this codebase's "even a clean result gets
    a documented, LOW-risk decision" convention (see BaseAgent)."""
    if not signals:
        return "low"
    return max((s.severity for s in signals), key=lambda sev: SEVERITY_ORDER[sev])
