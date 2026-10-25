"""
app.services.aging_calculations
==================================
Pure calculation core for AR aging and collection-priority scoring —
the deterministic engine behind `AgingService` (app.services.aging_service)
and `CollectionsAgent` (app.agents.collections.agent). Every function
here takes plain values (Decimal, date, str, uuid.UUID) and returns
plain dataclasses; nothing in this module touches a database session,
an ORM model, or an LLM. That split exists for the same reason
`TreasuryService._walk_events` and `FraudDetectionService`'s `_check_*`
methods are kept pure — see those modules' docstrings — taken one step
further here: this module doesn't import SQLAlchemy or Pydantic at
all, not even indirectly, so it can be imported and unit-tested in any
Python environment, including one where those packages aren't
installed. `AgingService` (a separate file) is the thin async layer
that fetches `ARInvoice`/`Customer` rows and feeds their fields into
the functions below.

WHAT COUNTS AS "OPEN" FOR AGING PURPOSES
------------------------------------------
An invoice is included in aging totals when `amount_outstanding > 0`
(`total_amount - amount_paid - amount_credited`, the same computed
property `ARInvoice` already exposes). A fully paid or fully credited
invoice naturally drops out of every bucket total without special
casing — `compute_invoice_aging` still computes a well-formed record
for it (bucket, days_overdue, amount_outstanding=0), it just carries
zero weight wherever invoices are summed. This is deliberately
different from `ARInvoiceRepository.list_overdue`/`list_due_within_range`,
which exclude only PAID/VOID and so still include DRAFT invoices —
correct for those callers (Treasury needs every committed receivable),
wrong for an aging report (a draft invoice was never sent to the
customer, so it isn't part of what they actually owe yet). See
`AgingService` for where DRAFT gets excluded at the query level.

AGING BUCKETS
-------------
Six buckets, inclusive on their upper bound, matching standard AR
aging convention: an invoice exactly 30 days overdue is "1-30", not
"31-60". `days_overdue <= 0` (not yet due, or due exactly today) is
"current" — it becomes 1-day-overdue starting the day after due_date.
See `tests/unit/test_aging_calculations.py` for every exact-boundary
case this is built and verified against.

COLLECTION PRIORITY SCORING
------------------------------
A points-based deterministic system, same spirit as
`FraudDetectionService`'s signal checks: four independent, individually
testable signals, each contributing a fixed number of points when it
fires, summed into one 0-100 `priority_score` capped for display
(the four signals can theoretically sum to 140; the cap never changes
tier classification since every threshold below sits under 100). None
of these point values are derived from this platform's own historical
collection-loss data (none exists yet) — same "v1 heuristic, named and
documented so a future recalibration has an obvious place to change
it" caveat as `FraudDetectionService`'s tuning constants.

The four signals:
    1. Age of the oldest overdue invoice — by far the strongest
       single signal in real AR practice. Reuses the exact same
       bucket_for_days_overdue used for the aging report itself, so a
       customer's score always traces back to a bucket a human can
       see on the aging table, not a second, separately-tuned age
       scale.
    2. What fraction of the customer's total outstanding balance sits
       in the 91+ day buckets ("severe aging exposure" per the product
       brief) — distinguishes "one old stray invoice on an otherwise
       current account" from "most of what they owe is badly overdue."
    3. Credit-limit position, only when `Customer.credit_limit` is
       set (NULL means unlimited — see that field's own docstring —
       so it contributes nothing here, not zero-as-in-safe). Over the
       limit means strictly greater, the same definition
       `AccountsReceivableAgent` uses, so the two agents can never
       disagree about whether the same customer is over their limit. A
       limit of exactly 0 is a real limit (no credit extended): any
       balance is over it, though the utilization *ratio* is undefined
       there and reported as null.
    4. Number of concurrently overdue invoices — a chronic slow payer
       with five small overdue invoices is a different (and arguably
       worse) collections problem than one customer with one large
       overdue invoice, even at the same dollar total.

`risk` and `priority` are DELIBERATELY the same computed tier in this
v1, not two independently-tuned numbers. The product brief lists them
as separate customer-level fields, but this platform has no separate
signal (e.g. a credit bureau feed) that would justify scoring
creditworthiness and collection urgency differently — both questions
reduce to "how concerning is this customer's receivable right now,"
so `CustomerAgingSummary` exposes one tier under both names rather
than silently maintaining two numbers that would always move in
lockstep. Documented here rather than left implicit, same as Budget
Planning's single signed variance_ratio.

RECOMMENDED PAYMENT-HISTORY SIGNAL — DELIBERATELY NOT INCLUDED
------------------------------------------------------------------
The product brief lists "available customer payment history" as a
signal to use "where already supported." Nothing in this platform
currently tracks *historical* payment timing (e.g. "this customer's
last 10 invoices averaged 12 days late") — `IncomingPayment` records
that cash arrived, not when it was due, and no service anywhere
aggregates paid-invoice timing into a reusable metric. Rather than
building a new historical-analytics subsystem inside what the product
brief scopes as a portfolio aging/prioritization feature, this is
named here as real, identified, not-yet-built follow-on work — same
practice as Tax Agent's docstring naming what it can't verify without
a persisted `tax_code` column.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from app.services.currency_utils import normalize_currency_code

# The four collection-priority tiers. A Literal (not an Enum) on purpose:
# these are the same lowercase strings `RiskLevel`'s values use, so
# `CollectionsAgent` can map them straight across, and FastAPI can
# validate a `?priority=` query param against them for free (an invalid
# value becomes a 422, not a silently empty result set).
PriorityTier = Literal["low", "medium", "high", "critical"]


class AgingBucket(str, Enum):
    CURRENT = "current"
    DAYS_1_30 = "1-30"
    DAYS_31_60 = "31-60"
    DAYS_61_90 = "61-90"
    DAYS_91_120 = "91-120"
    DAYS_121_PLUS = "121+"


# Ordered (upper_bound_days, bucket) pairs for everything past "current".
# Inclusive upper bounds — see module docstring.
_BUCKET_THRESHOLDS: tuple[tuple[int, AgingBucket], ...] = (
    (30, AgingBucket.DAYS_1_30),
    (60, AgingBucket.DAYS_31_60),
    (90, AgingBucket.DAYS_61_90),
    (120, AgingBucket.DAYS_91_120),
)


def compute_days_overdue(*, due_date: date, as_of: date) -> int:
    """Pure. Never negative — a not-yet-due invoice (due_date in the
    future relative to as_of) is 0 days overdue, not negative days."""
    return max(0, (as_of - due_date).days)


def bucket_for_days_overdue(days_overdue: int) -> AgingBucket:
    """Pure. See module docstring for bucket boundary convention."""
    if days_overdue <= 0:
        return AgingBucket.CURRENT
    for upper_bound, bucket in _BUCKET_THRESHOLDS:
        if days_overdue <= upper_bound:
            return bucket
    return AgingBucket.DAYS_121_PLUS


@dataclass(frozen=True)
class InvoiceAgingRecord:
    """One AR invoice's aging position as of a given date. Built by
    `compute_invoice_aging` from plain fields — never constructed
    directly from an ORM row, so it stays importable without
    SQLAlchemy. `amount_outstanding` can be zero (fully paid/credited)
    or, in a data-entry error scenario, negative (overpaid/overcredited);
    both are computed correctly and never raise — see module docstring
    on what "open" filtering does with each downstream."""

    invoice_id: uuid.UUID
    invoice_number: str
    customer_id: uuid.UUID
    customer_name: str
    invoice_date: date
    due_date: date
    as_of: date
    days_overdue: int
    bucket: AgingBucket
    total_amount: Decimal
    amount_paid: Decimal
    amount_credited: Decimal
    amount_outstanding: Decimal
    currency: str
    status: str


def compute_invoice_aging(
    *,
    invoice_id: uuid.UUID,
    invoice_number: str,
    customer_id: uuid.UUID,
    customer_name: str,
    invoice_date: date,
    due_date: date,
    total_amount: Decimal,
    amount_paid: Decimal,
    amount_credited: Decimal,
    currency: str,
    status: str,
    as_of: date,
) -> InvoiceAgingRecord:
    """Pure. The one place `amount_outstanding` and bucket assignment
    are computed for a single invoice — both the invoice-level and
    customer-level report builders in this module call this rather
    than recomputing either independently, so the two views can never
    silently disagree.

    `amount_outstanding = total - paid - credited` deliberately mirrors
    the existing `ARInvoice.amount_outstanding` property. This module
    can't call an ORM property (it must stay importable without
    SQLAlchemy), so the one-line formula is restated here rather than
    passed in; drift between the two is guarded by
    tests/integration/test_collections_agent.py, which asserts the
    aging record's outstanding equals the ORM property for seeded
    invoices (including partially paid and credited ones)."""
    amount_outstanding = total_amount - amount_paid - amount_credited
    overdue = compute_days_overdue(due_date=due_date, as_of=as_of)
    return InvoiceAgingRecord(
        invoice_id=invoice_id,
        invoice_number=invoice_number,
        customer_id=customer_id,
        customer_name=customer_name,
        invoice_date=invoice_date,
        due_date=due_date,
        as_of=as_of,
        days_overdue=overdue,
        bucket=bucket_for_days_overdue(overdue),
        total_amount=total_amount,
        amount_paid=amount_paid,
        amount_credited=amount_credited,
        amount_outstanding=amount_outstanding,
        currency=normalize_currency_code(currency),
        status=status,
    )


def _empty_bucket_totals() -> dict[AgingBucket, Decimal]:
    return {bucket: Decimal("0") for bucket in AgingBucket}


# --------------------------------------------------------------------------
# Collection priority scoring — see module docstring for the full
# rationale behind each signal and threshold below.
# --------------------------------------------------------------------------
_AGE_SCORE_BY_BUCKET: dict[AgingBucket, int] = {
    AgingBucket.CURRENT: 0,
    AgingBucket.DAYS_1_30: 10,
    AgingBucket.DAYS_31_60: 25,
    AgingBucket.DAYS_61_90: 45,
    AgingBucket.DAYS_91_120: 65,
    AgingBucket.DAYS_121_PLUS: 85,
}

SEVERE_EXPOSURE_MAJORITY_RATIO = Decimal("0.50")
SEVERE_EXPOSURE_MAJORITY_POINTS = 25
SEVERE_EXPOSURE_PARTIAL_RATIO = Decimal("0.25")
SEVERE_EXPOSURE_PARTIAL_POINTS = 15

CREDIT_OVER_LIMIT_POINTS = 20
CREDIT_NEAR_LIMIT_RATIO = Decimal("0.90")
CREDIT_NEAR_LIMIT_POINTS = 10

CHRONIC_OVERDUE_COUNT_HIGH = 5
CHRONIC_OVERDUE_COUNT_HIGH_POINTS = 10
CHRONIC_OVERDUE_COUNT_LOW = 2
CHRONIC_OVERDUE_COUNT_LOW_POINTS = 5

PRIORITY_SCORE_CAP = 100

CRITICAL_THRESHOLD = 70
HIGH_THRESHOLD = 45
MEDIUM_THRESHOLD = 20
# score < MEDIUM_THRESHOLD -> "low"

_RECOMMENDED_ACTION_BY_TIER: dict[PriorityTier, str] = {
    "low": "No action needed - account in good standing.",
    "medium": "Send a payment reminder and confirm the expected payment date.",
    "high": "Escalate to a formal collections follow up call; consider a partial credit hold.",
    "critical": "Escalate to collections/legal review and place the account on credit hold pending payment.",
}


@dataclass(frozen=True)
class _PriorityReason:
    points: int
    reason: str


def _score_oldest_invoice_age(oldest_days_overdue: int) -> _PriorityReason | None:
    if oldest_days_overdue <= 0:
        return None
    bucket = bucket_for_days_overdue(oldest_days_overdue)
    return _PriorityReason(
        points=_AGE_SCORE_BY_BUCKET[bucket],
        reason=(
            f"Oldest overdue invoice is {oldest_days_overdue} day(s) overdue "
            f"({bucket.value} bucket)."
        ),
    )


def _score_severe_exposure(
    *, total_outstanding: Decimal, amount_91_120: Decimal, amount_121_plus: Decimal
) -> _PriorityReason | None:
    if total_outstanding <= 0:
        return None
    severe = amount_91_120 + amount_121_plus
    if severe <= 0:
        return None
    ratio = severe / total_outstanding
    if ratio >= SEVERE_EXPOSURE_MAJORITY_RATIO:
        return _PriorityReason(
            points=SEVERE_EXPOSURE_MAJORITY_POINTS,
            reason=(
                f"{ratio:.0%} of this customer's outstanding balance is 91+ days overdue."
            ),
        )
    if ratio >= SEVERE_EXPOSURE_PARTIAL_RATIO:
        return _PriorityReason(
            points=SEVERE_EXPOSURE_PARTIAL_POINTS,
            reason=(
                f"{ratio:.0%} of this customer's outstanding balance is 91+ days overdue."
            ),
        )
    return None


def _score_credit_utilization(
    *, total_outstanding: Decimal, credit_limit: Decimal | None
) -> _PriorityReason | None:
    """Same over-limit definition as `AccountsReceivableAgent`: strictly
    greater than the limit. A limit of exactly 0 is a real limit ("no
    credit extended", legal per the `ge=0` on Customer's schema), so any
    balance at all is over it; utilization as a *ratio* is undefined at
    0, which is why the near-limit check below only runs when the limit
    is positive."""
    if credit_limit is None:
        return None
    if total_outstanding > credit_limit:
        return _PriorityReason(
            points=CREDIT_OVER_LIMIT_POINTS,
            reason=(
                f"Outstanding balance ({total_outstanding}) exceeds the customer's "
                f"credit limit ({credit_limit})."
            ),
        )
    if credit_limit > 0:
        ratio = total_outstanding / credit_limit
        if ratio >= CREDIT_NEAR_LIMIT_RATIO:
            return _PriorityReason(
                points=CREDIT_NEAR_LIMIT_POINTS,
                reason=f"Outstanding balance is {ratio:.0%} of the customer's credit limit.",
            )
    return None


def _score_overdue_invoice_count(overdue_invoice_count: int) -> _PriorityReason | None:
    if overdue_invoice_count >= CHRONIC_OVERDUE_COUNT_HIGH:
        return _PriorityReason(
            points=CHRONIC_OVERDUE_COUNT_HIGH_POINTS,
            reason=(
                f"{overdue_invoice_count} overdue invoices open at once - a chronic "
                f"pattern, not one late payment."
            ),
        )
    if overdue_invoice_count >= CHRONIC_OVERDUE_COUNT_LOW:
        return _PriorityReason(
            points=CHRONIC_OVERDUE_COUNT_LOW_POINTS,
            reason=f"{overdue_invoice_count} overdue invoices open at once.",
        )
    return None


def score_collection_priority(
    *,
    oldest_days_overdue: int,
    total_outstanding: Decimal,
    amount_91_120: Decimal,
    amount_121_plus: Decimal,
    credit_limit: Decimal | None,
    overdue_invoice_count: int,
) -> tuple[int, PriorityTier, list[str]]:
    """Pure. Returns (priority_score 0-100, tier, reasons) — see module
    docstring for the four signals and why `risk`/`priority` share one
    tier in this v1. `reasons` is never empty: a clean account gets one
    explicit reason saying so, matching this codebase's "a clean result
    still gets a documented decision" convention (see BaseAgent)."""
    candidates = [
        _score_oldest_invoice_age(oldest_days_overdue),
        _score_severe_exposure(
            total_outstanding=total_outstanding,
            amount_91_120=amount_91_120,
            amount_121_plus=amount_121_plus,
        ),
        _score_credit_utilization(total_outstanding=total_outstanding, credit_limit=credit_limit),
        _score_overdue_invoice_count(overdue_invoice_count),
    ]
    active = [c for c in candidates if c is not None]
    raw_score = sum(c.points for c in active)
    score = min(raw_score, PRIORITY_SCORE_CAP)

    tier: PriorityTier
    if score >= CRITICAL_THRESHOLD:
        tier = "critical"
    elif score >= HIGH_THRESHOLD:
        tier = "high"
    elif score >= MEDIUM_THRESHOLD:
        tier = "medium"
    else:
        tier = "low"

    reasons = [c.reason for c in active] or [
        "No overdue balance or elevated risk signal for this customer."
    ]
    return score, tier, reasons


def recommended_action_for_tier(tier: PriorityTier) -> str:
    return _RECOMMENDED_ACTION_BY_TIER.get(tier, _RECOMMENDED_ACTION_BY_TIER["low"])


@dataclass(frozen=True)
class CustomerCurrencyBalance:
    """One customer's position in one document currency."""
    currency: str
    total_outstanding: Decimal
    overdue_amount: Decimal
    current_amount: Decimal
    amount_1_30: Decimal
    amount_31_60: Decimal
    amount_61_90: Decimal
    amount_91_120: Decimal
    amount_121_plus: Decimal
    oldest_due_date: date | None
    oldest_days_overdue: int
    open_invoice_count: int
    overdue_invoice_count: int
    credit_limit: Decimal | None
    credit_utilization: Decimal | None
    priority_score: int
    risk: PriorityTier
    priority: PriorityTier
    priority_reasons: list[str] = field(default_factory=list)
    recommended_action: str = ""


@dataclass(frozen=True)
class CustomerAgingSummary:
    """One customer. Scalar monetary values are null for a mixed-currency book;
    use currency_balances for currency-scoped totals. No FX conversion is inferred."""
    customer_id: uuid.UUID
    customer_name: str
    currency: str | None
    as_of: date
    total_outstanding: Decimal | None
    overdue_amount: Decimal | None
    current_amount: Decimal | None
    amount_1_30: Decimal | None
    amount_31_60: Decimal | None
    amount_61_90: Decimal | None
    amount_91_120: Decimal | None
    amount_121_plus: Decimal | None
    oldest_due_date: date | None
    oldest_days_overdue: int
    open_invoice_count: int
    overdue_invoice_count: int
    credit_limit: Decimal | None
    credit_utilization: Decimal | None
    priority_score: int
    risk: PriorityTier
    priority: PriorityTier
    priority_reasons: list[str] = field(default_factory=list)
    recommended_action: str = ""
    currency_balances: list[CustomerCurrencyBalance] = field(default_factory=list)


def _summarize_customer_currency(
    *, customer_id: uuid.UUID, customer_name: str, currency: str,
    credit_limit: Decimal | None, invoices: list[InvoiceAgingRecord], as_of: date,
) -> CustomerAgingSummary:
    open_invoices = [inv for inv in invoices if inv.amount_outstanding > 0]
    bucket_totals = _empty_bucket_totals()
    for inv in open_invoices:
        bucket_totals[inv.bucket] += inv.amount_outstanding
    total = sum(bucket_totals.values(), Decimal("0"))
    overdue = [inv for inv in open_invoices if inv.days_overdue > 0]
    oldest = max(overdue, key=lambda inv: inv.days_overdue) if overdue else None
    oldest_date = oldest.due_date if oldest else None
    oldest_days = oldest.days_overdue if oldest else 0
    utilization = total / credit_limit if credit_limit is not None and credit_limit > 0 else None
    score, tier, reasons = score_collection_priority(
        oldest_days_overdue=oldest_days, total_outstanding=total,
        amount_91_120=bucket_totals[AgingBucket.DAYS_91_120],
        amount_121_plus=bucket_totals[AgingBucket.DAYS_121_PLUS],
        credit_limit=credit_limit, overdue_invoice_count=len(overdue),
    )
    return CustomerAgingSummary(
        customer_id=customer_id, customer_name=customer_name, currency=currency, as_of=as_of,
        total_outstanding=total, overdue_amount=total - bucket_totals[AgingBucket.CURRENT],
        current_amount=bucket_totals[AgingBucket.CURRENT], amount_1_30=bucket_totals[AgingBucket.DAYS_1_30],
        amount_31_60=bucket_totals[AgingBucket.DAYS_31_60], amount_61_90=bucket_totals[AgingBucket.DAYS_61_90],
        amount_91_120=bucket_totals[AgingBucket.DAYS_91_120], amount_121_plus=bucket_totals[AgingBucket.DAYS_121_PLUS],
        oldest_due_date=oldest_date, oldest_days_overdue=oldest_days,
        open_invoice_count=len(open_invoices), overdue_invoice_count=len(overdue),
        credit_limit=credit_limit, credit_utilization=utilization, priority_score=score,
        risk=tier, priority=tier, priority_reasons=reasons, recommended_action=recommended_action_for_tier(tier),
    )


def summarize_customer_aging(
    *, customer_id: uuid.UUID, customer_name: str, currency: str,
    credit_limit: Decimal | None, invoices: list[InvoiceAgingRecord], as_of: date,
) -> CustomerAgingSummary:
    """Summarize a customer without summing amounts across document currencies."""
    from dataclasses import replace
    default_currency = normalize_currency_code(currency)
    open_invoices = [inv for inv in invoices if inv.amount_outstanding > 0]
    grouped: dict[str, list[InvoiceAgingRecord]] = {}
    for inv in open_invoices:
        grouped.setdefault(normalize_currency_code(inv.currency), []).append(inv)
    if not grouped:
        return _summarize_customer_currency(
            customer_id=customer_id, customer_name=customer_name, currency=default_currency,
            credit_limit=credit_limit, invoices=[], as_of=as_of,
        )
    per_currency = [
        _summarize_customer_currency(
            customer_id=customer_id, customer_name=customer_name, currency=code,
            credit_limit=credit_limit if code == default_currency else None,
            invoices=grouped[code], as_of=as_of,
        ) for code in sorted(grouped)
    ]
    balances = [CustomerCurrencyBalance(
        currency=item.currency or "UNSPECIFIED",
        total_outstanding=item.total_outstanding or Decimal("0"),
        overdue_amount=item.overdue_amount or Decimal("0"),
        current_amount=item.current_amount or Decimal("0"),
        amount_1_30=item.amount_1_30 or Decimal("0"), amount_31_60=item.amount_31_60 or Decimal("0"),
        amount_61_90=item.amount_61_90 or Decimal("0"), amount_91_120=item.amount_91_120 or Decimal("0"),
        amount_121_plus=item.amount_121_plus or Decimal("0"), oldest_due_date=item.oldest_due_date,
        oldest_days_overdue=item.oldest_days_overdue, open_invoice_count=item.open_invoice_count,
        overdue_invoice_count=item.overdue_invoice_count, credit_limit=item.credit_limit,
        credit_utilization=item.credit_utilization, priority_score=item.priority_score, risk=item.risk,
        priority=item.priority, priority_reasons=item.priority_reasons, recommended_action=item.recommended_action,
    ) for item in per_currency]
    if len(per_currency) == 1:
        return replace(per_currency[0], currency_balances=balances)
    tier_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    highest = max(balances, key=lambda b: (tier_rank[b.priority], b.priority_score))
    oldest = max(balances, key=lambda b: b.oldest_days_overdue)
    reasons = [f"{b.currency}: {reason}" for b in balances for reason in b.priority_reasons]
    return CustomerAgingSummary(
        customer_id=customer_id, customer_name=customer_name, currency=None, as_of=as_of,
        total_outstanding=None, overdue_amount=None, current_amount=None, amount_1_30=None,
        amount_31_60=None, amount_61_90=None, amount_91_120=None, amount_121_plus=None,
        oldest_due_date=oldest.oldest_due_date, oldest_days_overdue=oldest.oldest_days_overdue,
        open_invoice_count=sum(b.open_invoice_count for b in balances),
        overdue_invoice_count=sum(b.overdue_invoice_count for b in balances), credit_limit=None,
        credit_utilization=None, priority_score=highest.priority_score, risk=highest.risk,
        priority=highest.priority, priority_reasons=reasons, recommended_action=highest.recommended_action,
        currency_balances=balances,
    )


@dataclass(frozen=True)
class PortfolioCurrencyBalance:
    """Portfolio totals for a single currency."""
    currency: str
    total_outstanding: Decimal
    overdue_amount: Decimal
    current_amount: Decimal
    amount_1_30: Decimal
    amount_31_60: Decimal
    amount_61_90: Decimal
    amount_91_120: Decimal
    amount_121_plus: Decimal
    open_invoice_count: int
    overdue_invoice_count: int
    customer_count: int
    oldest_days_overdue: int


@dataclass(frozen=True)
class PortfolioAgingSummary:
    """Flat amount fields are populated only for single-currency portfolios."""
    as_of: date
    total_outstanding: Decimal | None
    overdue_amount: Decimal | None
    current_amount: Decimal | None
    amount_1_30: Decimal | None
    amount_31_60: Decimal | None
    amount_61_90: Decimal | None
    amount_91_120: Decimal | None
    amount_121_plus: Decimal | None
    open_invoice_count: int
    overdue_invoice_count: int
    customer_count: int
    oldest_days_overdue: int
    currency: str | None = None
    currency_balances: list[PortfolioCurrencyBalance] = field(default_factory=list)


def summarize_portfolio_aging(*, as_of: date, invoices: list[InvoiceAgingRecord]) -> PortfolioAgingSummary:
    """Aggregate the AR portfolio by normalized document currency, no FX conversion."""
    open_invoices = [inv for inv in invoices if inv.amount_outstanding > 0]
    grouped: dict[str, list[InvoiceAgingRecord]] = {}
    for inv in open_invoices:
        grouped.setdefault(normalize_currency_code(inv.currency), []).append(inv)
    balances = []
    for code, rows in sorted(grouped.items()):
        buckets = _empty_bucket_totals()
        for inv in rows:
            buckets[inv.bucket] += inv.amount_outstanding
        total = sum(buckets.values(), Decimal("0"))
        overdue = [inv for inv in rows if inv.days_overdue > 0]
        balances.append(PortfolioCurrencyBalance(
            currency=code, total_outstanding=total, overdue_amount=total-buckets[AgingBucket.CURRENT],
            current_amount=buckets[AgingBucket.CURRENT], amount_1_30=buckets[AgingBucket.DAYS_1_30],
            amount_31_60=buckets[AgingBucket.DAYS_31_60], amount_61_90=buckets[AgingBucket.DAYS_61_90],
            amount_91_120=buckets[AgingBucket.DAYS_91_120], amount_121_plus=buckets[AgingBucket.DAYS_121_PLUS],
            open_invoice_count=len(rows), overdue_invoice_count=len(overdue),
            customer_count=len({i.customer_id for i in rows}), oldest_days_overdue=max((i.days_overdue for i in overdue), default=0),
        ))
    overdue_all = [inv for inv in open_invoices if inv.days_overdue > 0]
    common = dict(as_of=as_of, open_invoice_count=len(open_invoices), overdue_invoice_count=len(overdue_all),
                  customer_count=len({i.customer_id for i in open_invoices}),
                  oldest_days_overdue=max((i.days_overdue for i in overdue_all), default=0), currency_balances=balances)
    if len(balances) == 1:
        b=balances[0]
        return PortfolioAgingSummary(**common, currency=b.currency, total_outstanding=b.total_outstanding,
            overdue_amount=b.overdue_amount, current_amount=b.current_amount, amount_1_30=b.amount_1_30,
            amount_31_60=b.amount_31_60, amount_61_90=b.amount_61_90, amount_91_120=b.amount_91_120, amount_121_plus=b.amount_121_plus)
    if not balances:
        return PortfolioAgingSummary(**common, currency=None, total_outstanding=Decimal("0"), overdue_amount=Decimal("0"),
            current_amount=Decimal("0"), amount_1_30=Decimal("0"), amount_31_60=Decimal("0"), amount_61_90=Decimal("0"),
            amount_91_120=Decimal("0"), amount_121_plus=Decimal("0"))
    return PortfolioAgingSummary(**common, currency=None, total_outstanding=None, overdue_amount=None, current_amount=None,
        amount_1_30=None, amount_31_60=None, amount_61_90=None, amount_91_120=None, amount_121_plus=None)


def expand_customer_aging_by_currency(summary: CustomerAgingSummary) -> list[CustomerAgingSummary]:
    """Return one currency-scoped customer summary per balance for agent impacts."""
    from dataclasses import replace
    if len(summary.currency_balances) <= 1:
        return [summary]
    return [replace(summary, currency=b.currency, total_outstanding=b.total_outstanding,
        overdue_amount=b.overdue_amount, current_amount=b.current_amount, amount_1_30=b.amount_1_30,
        amount_31_60=b.amount_31_60, amount_61_90=b.amount_61_90, amount_91_120=b.amount_91_120,
        amount_121_plus=b.amount_121_plus, oldest_due_date=b.oldest_due_date,
        oldest_days_overdue=b.oldest_days_overdue, open_invoice_count=b.open_invoice_count,
        overdue_invoice_count=b.overdue_invoice_count, credit_limit=b.credit_limit,
        credit_utilization=b.credit_utilization, priority_score=b.priority_score, risk=b.risk, priority=b.priority,
        priority_reasons=b.priority_reasons, recommended_action=b.recommended_action, currency_balances=[b])
        for b in summary.currency_balances]


# --------------------------------------------------------------------------
# Deterministic ordering. Both list endpoints paginate over Python lists
# built from an unordered SQL result, and many rows legitimately tie on
# the primary sort value (every not-yet-due invoice has days_overdue == 0;
# two customers can share a priority_score). Without a full tiebreaker,
# the same request could return a different row order between page 1 and
# page 2 and silently duplicate or skip rows across page boundaries.
# These keys make the order total and stable.
# --------------------------------------------------------------------------
def invoice_sort_key(record: InvoiceAgingRecord) -> tuple[int, Decimal, str, str]:
    """Most overdue first; ties broken by larger outstanding balance,
    then invoice number, then invoice id (so two rows can never compare
    equal)."""
    return (
        -record.days_overdue,
        -record.amount_outstanding,
        record.invoice_number,
        str(record.invoice_id),
    )


def customer_sort_key(summary: CustomerAgingSummary) -> tuple[int, Decimal, str, str]:
    """Highest priority score first; ties broken by larger outstanding
    balance, then customer name (case-insensitive), then customer id."""
    return (
        -summary.priority_score,
        -(summary.total_outstanding if summary.total_outstanding is not None else Decimal("0")),
        summary.customer_name.lower(),
        str(summary.customer_id),
    )
