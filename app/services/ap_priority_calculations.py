"""
app.services.ap_priority_calculations
=========================================
Pure calculation core for AP payment prioritization — this is money
owed BY the company, the counterpart to
`app.services.aging_calculations` (money owed TO the company). Same
split for the same reason: nothing here imports SQLAlchemy, Pydantic,
or anything else from this app, so it stays importable and unit
testable in an environment with none of this project's third-party
dependencies installed. `APPriorityService` (a separate file) is the
async layer that fetches `Invoice`/`OutgoingPayment`/`Vendor` rows and
feeds their fields into the functions below.

THIS IS DELIBERATELY SIMPLER THAN aging_calculations — AND THAT'S THE
PRODUCT BRIEF'S OWN CALL, NOT A SHORTCUT HERE
----------------------------------------------------------------------
The brief's own collections section (§3C) spells out a multi-signal,
documented scoring engine in detail. Its AP section (§4) asks only for
"priority" and "reason" per obligation, with no scoring rubric
specified. So this module uses two signals, not four, and both are
named in code the same way — not because the AP side matters less, but
because adding signals nothing asked for would be the exact
over-engineering the brief explicitly warns against elsewhere (§38).

WHY AP INVOICES DON'T NEED AN "OUTSTANDING AMOUNT" THE WAY AR DOES
------------------------------------------------------------------------
`ARInvoice` tracks partial payments directly (`amount_paid`,
`amount_credited`) because a customer can pay part of an invoice.
`OutgoingPayment.invoice_id` is unique — see `app.services
.payment_service` — so an AP invoice is paid in exactly one shot or not
at all. There is no partial-payment or outstanding-balance concept to
compute here; `Invoice.total_amount` IS the full obligation until the
invoice reaches PAID.

THE STATUS TAXONOMY, AND ONE CATEGORY THE PRODUCT BRIEF DOESN'T NAME
--------------------------------------------------------------------------
`Invoice.status` and `OutgoingPayment.status` together produce six
mutually exclusive priority statuses:

    BLOCKED            Invoice.status == MATCH_FAILED — stuck in the
                       3-way match step itself (the brief's own
                       "invoices blocked by 3-way-match issues").
    PAYMENT_FAILED     A payment was scheduled and then failed. NOT
                       named in the product brief's category list, and
                       added here based on a real finding while
                       inspecting app.services.payment_service for this
                       feature: once `OutgoingPayment.status` becomes
                       FAILED, nothing in this codebase resets the
                       invoice back to APPROVED or allows a second
                       payment row for the same invoice (the unique
                       constraint on `invoice_id` forbids it) — so a
                       failed payment is not just "overdue," it is
                       permanently stuck without a human stepping in
                       through some path this session didn't build.
                       Leaving it out of this feature's categories
                       would make that stuck state invisible, which is
                       a worse outcome than naming a category the brief
                       didn't ask for. Fixing the stuck state itself
                       (a retry/reschedule path) is out of scope here —
                       named as real follow-on work, not silently
                       patched over.
    AWAITING_APPROVAL  Invoice.status == MATCHED (successfully matched,
                       not yet approved — see app.services
                       .ap_priority_service module docstring for why
                       this is MATCHED and not InvoiceStatus
                       .PENDING_APPROVAL, which turned out to be an
                       unused enum member), OR
                       Invoice.status == SCHEDULED_FOR_PAYMENT and the
                       payment's own status is PENDING_APPROVAL (the
                       invoice cleared approval but the payment needs
                       its own separate sign-off). Both are folded into
                       one category because the actionable ask is the
                       same — "someone needs to approve something" —
                       but `reason` always says which kind, so this
                       folding never hides the distinction from a
                       reader.
    READY_TO_SCHEDULE  Invoice.status == APPROVED, no payment row yet.
                       This is the actual "payment obligation" the
                       brief's due-date buckets are about: approved,
                       payable, and nobody has decided when yet.
    SCHEDULED          A payment row exists with status SCHEDULED,
                       APPROVED, or EXECUTING — in motion.
    EXECUTED           Invoice.status == PAID.

PRIORITY SCORING — TWO SIGNALS, THRESHOLDS NAMED IN CODE
----------------------------------------------------------------
1. Status severity — a fixed point value per status above (BLOCKED and
   PAYMENT_FAILED score highest: both represent a process stuck on
   something other than "nobody's gotten to it yet").
2. Due-date urgency — overdue (scaled by how overdue), due today, due
   within 7 days, due within 30 days, or later; applied on top of the
   status points for every status except EXECUTED (nothing left to be
   urgent about once it's paid), so "blocked AND overdue" correctly
   scores higher than "blocked but not yet due."

Summed and capped at 100, same LOW/MEDIUM/HIGH/CRITICAL tier shape as
`aging_calculations`, with independently documented thresholds — the
two modules share a vocabulary, not a scoring table; see that module's
own docstring if comparing the two.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from app.services.currency_utils import normalize_currency_code

PriorityTier = Literal["low", "medium", "high", "critical"]


class PaymentPriorityStatus(str, Enum):
    BLOCKED = "blocked"
    PAYMENT_FAILED = "payment_failed"
    AWAITING_APPROVAL = "awaiting_approval"
    READY_TO_SCHEDULE = "ready_to_schedule"
    SCHEDULED = "scheduled"
    EXECUTED = "executed"


class DueBucket(str, Enum):
    OVERDUE = "overdue"
    DUE_TODAY = "due_today"
    DUE_WITHIN_7 = "due_within_7"
    DUE_WITHIN_30 = "due_within_30"
    DUE_LATER = "due_later"
    NOT_APPLICABLE = "not_applicable"  # EXECUTED rows only


def compute_days_until_due(*, due_date: date, as_of: date) -> int:
    """Pure. Positive = still ahead, 0 = due today, negative = overdue
    by that many days. Unlike aging_calculations.compute_days_overdue,
    this does NOT clamp at 0 — the sign is how callers tell "overdue"
    from "not yet due," and DueBucket below is what turns it into a
    category."""
    return (due_date - as_of).days


def bucket_for_days_until_due(days_until_due: int) -> DueBucket:
    """Pure. due_date in the past (negative) -> OVERDUE; 0 -> DUE_TODAY;
    otherwise the usual 7/30-day windows, inclusive on their upper
    bound (due in exactly 7 days is DUE_WITHIN_7, not DUE_WITHIN_30)."""
    if days_until_due < 0:
        return DueBucket.OVERDUE
    if days_until_due == 0:
        return DueBucket.DUE_TODAY
    if days_until_due <= 7:
        return DueBucket.DUE_WITHIN_7
    if days_until_due <= 30:
        return DueBucket.DUE_WITHIN_30
    return DueBucket.DUE_LATER


# --------------------------------------------------------------------------
# Scoring — see module docstring for the full rationale.
# --------------------------------------------------------------------------
_STATUS_POINTS: dict[PaymentPriorityStatus, int] = {
    PaymentPriorityStatus.PAYMENT_FAILED: 50,
    PaymentPriorityStatus.BLOCKED: 35,
    PaymentPriorityStatus.AWAITING_APPROVAL: 20,
    PaymentPriorityStatus.READY_TO_SCHEDULE: 0,
    PaymentPriorityStatus.SCHEDULED: 0,
    PaymentPriorityStatus.EXECUTED: 0,
}

OVERDUE_1_TO_7_DAYS_POINTS = 20
OVERDUE_8_TO_30_DAYS_POINTS = 45
OVERDUE_31_PLUS_DAYS_POINTS = 70
DUE_TODAY_POINTS = 15
DUE_WITHIN_7_POINTS = 8
DUE_WITHIN_30_POINTS = 0
DUE_LATER_POINTS = 0

PRIORITY_SCORE_CAP = 100
CRITICAL_THRESHOLD = 70
HIGH_THRESHOLD = 40
MEDIUM_THRESHOLD = 15
# score < MEDIUM_THRESHOLD -> "low"

_REASON_BY_STATUS: dict[PaymentPriorityStatus, str] = {
    PaymentPriorityStatus.BLOCKED: "Blocked by a 3-way match issue — needs review before it can be approved.",
    PaymentPriorityStatus.PAYMENT_FAILED: "A scheduled payment attempt failed and has not been retried.",
    PaymentPriorityStatus.AWAITING_APPROVAL: "Awaiting approval before it can be paid.",
    PaymentPriorityStatus.READY_TO_SCHEDULE: "Approved and payable — not yet scheduled.",
    PaymentPriorityStatus.SCHEDULED: "Payment is scheduled and in progress.",
    PaymentPriorityStatus.EXECUTED: "Payment has been executed.",
}


def _due_points(bucket: DueBucket, days_until_due: int) -> int:
    if bucket == DueBucket.NOT_APPLICABLE:
        return 0
    if bucket == DueBucket.OVERDUE:
        days_overdue = -days_until_due
        if days_overdue <= 7:
            return OVERDUE_1_TO_7_DAYS_POINTS
        if days_overdue <= 30:
            return OVERDUE_8_TO_30_DAYS_POINTS
        return OVERDUE_31_PLUS_DAYS_POINTS
    return {
        DueBucket.DUE_TODAY: DUE_TODAY_POINTS,
        DueBucket.DUE_WITHIN_7: DUE_WITHIN_7_POINTS,
        DueBucket.DUE_WITHIN_30: DUE_WITHIN_30_POINTS,
        DueBucket.DUE_LATER: DUE_LATER_POINTS,
    }[bucket]


def score_payment_priority(
    *, status: PaymentPriorityStatus, due_bucket: DueBucket, days_until_due: int
) -> tuple[int | None, PriorityTier | None]:
    """Pure. Returns (score, tier) — both None for EXECUTED, since a
    paid invoice has no remaining priority to assess (not the same as
    "low priority", which still means "needs eventual attention")."""
    if status == PaymentPriorityStatus.EXECUTED:
        return None, None
    raw = _STATUS_POINTS[status] + _due_points(due_bucket, days_until_due)
    score = min(raw, PRIORITY_SCORE_CAP)
    if score >= CRITICAL_THRESHOLD:
        tier: PriorityTier = "critical"
    elif score >= HIGH_THRESHOLD:
        tier = "high"
    elif score >= MEDIUM_THRESHOLD:
        tier = "medium"
    else:
        tier = "low"
    return score, tier


def build_reason(
    *, status: PaymentPriorityStatus, due_bucket: DueBucket, days_until_due: int, detail: str | None
) -> str:
    """Pure. `detail` is status-specific context the caller already has
    from the ORM row (match_type for BLOCKED, failure_reason for
    PAYMENT_FAILED) — kept as a separate parameter rather than looked
    up here so this stays a pure function with no DB access."""
    base = _REASON_BY_STATUS[status]
    if detail:
        base = f"{base} ({detail})"
    if status in (PaymentPriorityStatus.READY_TO_SCHEDULE, PaymentPriorityStatus.SCHEDULED):
        if due_bucket == DueBucket.OVERDUE:
            base += f" {-days_until_due} day(s) overdue."
        elif due_bucket == DueBucket.DUE_TODAY:
            base += " Due today."
        elif due_bucket == DueBucket.DUE_WITHIN_7:
            base += f" Due in {days_until_due} day(s)."
    return base


@dataclass(frozen=True)
class PaymentObligation:
    """One AP invoice's payment-priority position as of a given date.
    Built by `compute_payment_obligation` from plain fields — never
    constructed directly from an ORM row, so this stays importable
    without SQLAlchemy."""

    invoice_id: uuid.UUID
    invoice_number: str
    vendor_id: uuid.UUID
    vendor_name: str
    amount: Decimal
    currency: str
    due_date: date
    as_of: date
    days_until_due: int
    due_bucket: DueBucket
    status: PaymentPriorityStatus
    priority_score: int | None
    priority: PriorityTier | None
    reason: str
    scheduled_date: date | None = None
    executed_date: date | None = None


def compute_payment_obligation(
    *,
    invoice_id: uuid.UUID,
    invoice_number: str,
    vendor_id: uuid.UUID,
    vendor_name: str,
    amount: Decimal,
    currency: str,
    due_date: date,
    as_of: date,
    status: PaymentPriorityStatus,
    status_detail: str | None = None,
    scheduled_date: date | None = None,
    executed_date: date | None = None,
) -> PaymentObligation:
    days_until_due = compute_days_until_due(due_date=due_date, as_of=as_of)
    due_bucket = (
        DueBucket.NOT_APPLICABLE
        if status == PaymentPriorityStatus.EXECUTED
        else bucket_for_days_until_due(days_until_due)
    )
    score, tier = score_payment_priority(
        status=status, due_bucket=due_bucket, days_until_due=days_until_due
    )
    reason = build_reason(
        status=status, due_bucket=due_bucket, days_until_due=days_until_due, detail=status_detail
    )
    return PaymentObligation(
        invoice_id=invoice_id,
        invoice_number=invoice_number,
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        amount=amount,
        currency=normalize_currency_code(currency),
        due_date=due_date,
        as_of=as_of,
        days_until_due=days_until_due,
        due_bucket=due_bucket,
        status=status,
        priority_score=score,
        priority=tier,
        reason=reason,
        scheduled_date=scheduled_date,
        executed_date=executed_date,
    )


@dataclass(frozen=True)
class VendorCurrencyExposure:
    """One vendor's open AP exposure in one explicit currency."""

    currency: str
    total_exposure: Decimal
    open_invoice_count: int
    overdue_amount: Decimal
    overdue_invoice_count: int
    blocked_count: int
    payment_failed_count: int
    awaiting_approval_count: int
    highest_priority: PriorityTier


@dataclass(frozen=True)
class VendorExposureSummary:
    """Vendor exposure with no cross-currency monetary arithmetic."""

    vendor_id: uuid.UUID
    vendor_name: str
    currency: str | None
    total_exposure: Decimal | None
    open_invoice_count: int
    overdue_amount: Decimal | None
    overdue_invoice_count: int
    blocked_count: int
    payment_failed_count: int
    awaiting_approval_count: int
    highest_priority: PriorityTier
    currency_balances: list[VendorCurrencyExposure] = field(default_factory=list)


@dataclass(frozen=True)
class APPriorityCurrencySummary:
    """Portfolio status amounts and totals expressed in one currency."""

    currency: str
    total_payable: Decimal
    open_obligation_count: int
    overdue_amount: Decimal
    overdue_count: int
    by_status_count: dict[str, int]
    by_status_amount: dict[str, Decimal]
    executed_last_30_days_amount: Decimal
    executed_last_30_days_count: int


_TIER_RANK: dict[PriorityTier, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _summarize_vendor_currency(
    currency: str, obligations: list[PaymentObligation]
) -> VendorCurrencyExposure:
    open_obligations = [
        obligation
        for obligation in obligations
        if obligation.status != PaymentPriorityStatus.EXECUTED
    ]
    overdue = [
        obligation
        for obligation in open_obligations
        if obligation.due_bucket == DueBucket.OVERDUE
    ]
    highest_rank = max(
        (
            _TIER_RANK[obligation.priority]
            for obligation in open_obligations
            if obligation.priority is not None
        ),
        default=0,
    )
    highest_priority = next(
        tier for tier, rank in _TIER_RANK.items() if rank == highest_rank
    )
    return VendorCurrencyExposure(
        currency=currency,
        total_exposure=sum((obligation.amount for obligation in open_obligations), Decimal("0")),
        open_invoice_count=len(open_obligations),
        overdue_amount=sum((obligation.amount for obligation in overdue), Decimal("0")),
        overdue_invoice_count=len(overdue),
        blocked_count=sum(
            obligation.status == PaymentPriorityStatus.BLOCKED
            for obligation in open_obligations
        ),
        payment_failed_count=sum(
            obligation.status == PaymentPriorityStatus.PAYMENT_FAILED
            for obligation in open_obligations
        ),
        awaiting_approval_count=sum(
            obligation.status == PaymentPriorityStatus.AWAITING_APPROVAL
            for obligation in open_obligations
        ),
        highest_priority=highest_priority,
    )


def summarize_vendor_exposure(
    *,
    vendor_id: uuid.UUID,
    vendor_name: str,
    currency: str,
    obligations: list[PaymentObligation],
) -> VendorExposureSummary:
    """Aggregate one vendor by document currency, never the default currency."""
    open_obligations = [
        obligation
        for obligation in obligations
        if obligation.status != PaymentPriorityStatus.EXECUTED
    ]
    grouped: dict[str, list[PaymentObligation]] = {}
    for obligation in open_obligations:
        code = normalize_currency_code(obligation.currency)
        grouped.setdefault(code, []).append(obligation)

    balances = [
        _summarize_vendor_currency(code, grouped[code])
        for code in sorted(grouped)
    ]
    if not balances:
        return VendorExposureSummary(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            currency=normalize_currency_code(currency),
            total_exposure=Decimal("0"),
            open_invoice_count=0,
            overdue_amount=Decimal("0"),
            overdue_invoice_count=0,
            blocked_count=0,
            payment_failed_count=0,
            awaiting_approval_count=0,
            highest_priority="low",
        )

    highest_priority = max(
        (balance.highest_priority for balance in balances),
        key=lambda tier: _TIER_RANK[tier],
    )
    if len(balances) == 1:
        balance = balances[0]
        return VendorExposureSummary(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            currency=balance.currency,
            total_exposure=balance.total_exposure,
            open_invoice_count=balance.open_invoice_count,
            overdue_amount=balance.overdue_amount,
            overdue_invoice_count=balance.overdue_invoice_count,
            blocked_count=balance.blocked_count,
            payment_failed_count=balance.payment_failed_count,
            awaiting_approval_count=balance.awaiting_approval_count,
            highest_priority=highest_priority,
            currency_balances=balances,
        )

    return VendorExposureSummary(
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        currency=None,
        total_exposure=None,
        open_invoice_count=sum(balance.open_invoice_count for balance in balances),
        overdue_amount=None,
        overdue_invoice_count=sum(balance.overdue_invoice_count for balance in balances),
        blocked_count=sum(balance.blocked_count for balance in balances),
        payment_failed_count=sum(balance.payment_failed_count for balance in balances),
        awaiting_approval_count=sum(balance.awaiting_approval_count for balance in balances),
        highest_priority=highest_priority,
        currency_balances=balances,
    )


def summarize_ap_priority(
    *, as_of: date, obligations: list[PaymentObligation]
) -> dict:
    """Aggregate AP amounts by currency without foreign-exchange conversion."""
    open_obligations = [
        obligation
        for obligation in obligations
        if obligation.status != PaymentPriorityStatus.EXECUTED
    ]
    overall_status_counts: dict[str, int] = {}
    for obligation in open_obligations:
        status_code = obligation.status.value
        overall_status_counts[status_code] = overall_status_counts.get(status_code, 0) + 1

    grouped: dict[str, list[PaymentObligation]] = {}
    for obligation in obligations:
        code = normalize_currency_code(obligation.currency)
        grouped.setdefault(code, []).append(obligation)

    currency_balances: list[APPriorityCurrencySummary] = []
    for code, rows in sorted(grouped.items()):
        currency_open = [
            obligation
            for obligation in rows
            if obligation.status != PaymentPriorityStatus.EXECUTED
        ]
        overdue = [
            obligation
            for obligation in currency_open
            if obligation.due_bucket == DueBucket.OVERDUE
        ]
        by_status_count: dict[str, int] = {}
        by_status_amount: dict[str, Decimal] = {}
        for obligation in currency_open:
            status_code = obligation.status.value
            by_status_count[status_code] = by_status_count.get(status_code, 0) + 1
            by_status_amount[status_code] = (
                by_status_amount.get(status_code, Decimal("0")) + obligation.amount
            )

        executed = [
            obligation
            for obligation in rows
            if obligation.status == PaymentPriorityStatus.EXECUTED
        ]
        currency_balances.append(
            APPriorityCurrencySummary(
                currency=code,
                total_payable=sum(
                    (obligation.amount for obligation in currency_open), Decimal("0")
                ),
                open_obligation_count=len(currency_open),
                overdue_amount=sum(
                    (obligation.amount for obligation in overdue), Decimal("0")
                ),
                overdue_count=len(overdue),
                by_status_count=by_status_count,
                by_status_amount=by_status_amount,
                executed_last_30_days_amount=sum(
                    (obligation.amount for obligation in executed), Decimal("0")
                ),
                executed_last_30_days_count=len(executed),
            )
        )

    executed = [
        obligation
        for obligation in obligations
        if obligation.status == PaymentPriorityStatus.EXECUTED
    ]
    common = {
        "as_of": as_of,
        "open_obligation_count": len(open_obligations),
        "overdue_count": sum(
            obligation.due_bucket == DueBucket.OVERDUE
            for obligation in open_obligations
        ),
        "by_status_count": overall_status_counts,
        "executed_last_30_days_count": len(executed),
        "currency_balances": currency_balances,
    }

    if len(currency_balances) == 1:
        balance = currency_balances[0]
        return {
            **common,
            "currency": balance.currency,
            "total_payable": balance.total_payable,
            "overdue_amount": balance.overdue_amount,
            "by_status_amount": balance.by_status_amount,
            "executed_last_30_days_amount": balance.executed_last_30_days_amount,
        }
    if not currency_balances:
        return {
            **common,
            "currency": None,
            "total_payable": Decimal("0"),
            "overdue_amount": Decimal("0"),
            "by_status_amount": {},
            "executed_last_30_days_amount": Decimal("0"),
        }
    return {
        **common,
        "currency": None,
        "total_payable": None,
        "overdue_amount": None,
        "by_status_amount": {},
        "executed_last_30_days_amount": None,
    }


def obligation_sort_key(o: PaymentObligation) -> tuple[int, Decimal, str, str]:
    """Highest priority score first (EXECUTED/no-score rows sort last,
    not first); ties broken by larger amount, then invoice number, then
    id — see aging_calculations.invoice_sort_key for why a total order
    matters once pagination is involved."""
    return (
        -(o.priority_score if o.priority_score is not None else -1),
        -o.amount,
        o.invoice_number,
        str(o.invoice_id),
    )


def vendor_sort_key(v: VendorExposureSummary) -> tuple[int, Decimal, str, str]:
    return (
        -_TIER_RANK[v.highest_priority],
        -(v.total_exposure if v.total_exposure is not None else Decimal("0")),
        v.vendor_name.lower(),
        str(v.vendor_id),
    )
