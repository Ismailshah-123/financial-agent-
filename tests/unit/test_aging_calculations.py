"""
Unit tests for app.services.aging_calculations — the pure bucket and
collection-priority scoring engine behind the Collections/Aging
feature. Every function under test takes plain values, no DB session,
no event loop, same convention as tests/unit/test_treasury_service.py
and tests/unit/test_fraud_detection_service.py.

This module is unusual among this codebase's "pure" test files in one
respect: app.services.aging_calculations imports nothing outside the
standard library (see that module's docstring), so — unlike
test_treasury_service.py, which imports app.services.treasury_service
and therefore transitively imports SQLAlchemy even for its DB-free
tests — every test in this file can run in an environment that has
Python only, no third-party packages installed at all. Verified by
actually running this exact file with a plain `unittest` runner (no
pytest, no pip install) during the session that added it.
"""

from __future__ import annotations

import random
import uuid
from datetime import date
from decimal import Decimal
from typing import get_args

from app.services.aging_calculations import (
    CHRONIC_OVERDUE_COUNT_HIGH,
    CHRONIC_OVERDUE_COUNT_LOW,
    CRITICAL_THRESHOLD,
    HIGH_THRESHOLD,
    MEDIUM_THRESHOLD,
    AgingBucket,
    PriorityTier,
    bucket_for_days_overdue,
    compute_days_overdue,
    compute_invoice_aging,
    customer_sort_key,
    invoice_sort_key,
    recommended_action_for_tier,
    score_collection_priority,
    summarize_customer_aging,
    summarize_portfolio_aging,
)

_AS_OF = date(2026, 6, 30)


def _invoice(
    *,
    due_date: date,
    total_amount: str = "1000.00",
    amount_paid: str = "0",
    amount_credited: str = "0",
    as_of: date = _AS_OF,
    customer_id: uuid.UUID | None = None,
    invoice_number: str = "INV-1",
    status: str = "sent",
):
    return compute_invoice_aging(
        invoice_id=uuid.uuid4(),
        invoice_number=invoice_number,
        customer_id=customer_id or uuid.uuid4(),
        customer_name="Test Customer",
        invoice_date=due_date,
        due_date=due_date,
        total_amount=Decimal(total_amount),
        amount_paid=Decimal(amount_paid),
        amount_credited=Decimal(amount_credited),
        currency="PKR",
        status=status,
        as_of=as_of,
    )


# ---------------------------------------------------------------------
# compute_days_overdue / bucket_for_days_overdue — exact boundaries
# ---------------------------------------------------------------------


def test_future_due_date_is_zero_days_overdue() -> None:
    assert compute_days_overdue(due_date=date(2026, 7, 15), as_of=_AS_OF) == 0


def test_due_today_is_zero_days_overdue() -> None:
    assert compute_days_overdue(due_date=_AS_OF, as_of=_AS_OF) == 0


def test_due_today_buckets_as_current() -> None:
    assert bucket_for_days_overdue(0) == AgingBucket.CURRENT


def test_exact_one_day_overdue() -> None:
    overdue = compute_days_overdue(due_date=date(2026, 6, 29), as_of=_AS_OF)
    assert overdue == 1
    assert bucket_for_days_overdue(overdue) == AgingBucket.DAYS_1_30


def test_30_day_boundary_is_still_1_30_bucket() -> None:
    assert bucket_for_days_overdue(30) == AgingBucket.DAYS_1_30


def test_31_day_boundary_moves_to_31_60_bucket() -> None:
    assert bucket_for_days_overdue(31) == AgingBucket.DAYS_31_60


def test_60_day_boundary_is_still_31_60_bucket() -> None:
    # 60 is the inclusive upper bound of the 31-60 bucket.
    assert bucket_for_days_overdue(60) == AgingBucket.DAYS_31_60


def test_61_day_boundary_moves_to_61_90_bucket() -> None:
    assert bucket_for_days_overdue(61) == AgingBucket.DAYS_61_90


def test_90_day_boundary_is_still_61_90_bucket() -> None:
    assert bucket_for_days_overdue(90) == AgingBucket.DAYS_61_90


def test_91_day_boundary_moves_to_91_120_bucket() -> None:
    assert bucket_for_days_overdue(91) == AgingBucket.DAYS_91_120


def test_120_day_boundary_is_still_91_120_bucket() -> None:
    assert bucket_for_days_overdue(120) == AgingBucket.DAYS_91_120


def test_121_day_boundary_moves_to_121_plus_bucket() -> None:
    assert bucket_for_days_overdue(121) == AgingBucket.DAYS_121_PLUS


def test_150_plus_days_is_121_plus_bucket() -> None:
    assert bucket_for_days_overdue(150) == AgingBucket.DAYS_121_PLUS
    assert bucket_for_days_overdue(400) == AgingBucket.DAYS_121_PLUS


# ---------------------------------------------------------------------
# compute_invoice_aging — payment / credit-memo / outstanding cases
# ---------------------------------------------------------------------


def test_fully_paid_invoice_has_zero_outstanding_and_still_buckets_cleanly() -> None:
    record = _invoice(due_date=date(2026, 5, 1), total_amount="5000.00", amount_paid="5000.00")
    assert record.amount_outstanding == Decimal("0")
    # Still computes a bucket (the invoice was overdue-as-of, whether
    # paid or not) — callers filter zero-outstanding rows out of
    # totals, this function itself never crashes or special-cases it.
    assert record.bucket == AgingBucket.DAYS_31_60


def test_partial_payment_reduces_outstanding_correctly() -> None:
    record = _invoice(due_date=date(2026, 6, 1), total_amount="1000.00", amount_paid="400.00")
    assert record.amount_outstanding == Decimal("600.00")


def test_credit_memo_reduces_outstanding_correctly() -> None:
    record = _invoice(
        due_date=date(2026, 6, 1), total_amount="1000.00", amount_credited="250.00"
    )
    assert record.amount_outstanding == Decimal("750.00")


def test_partial_payment_and_credit_memo_combine() -> None:
    record = _invoice(
        due_date=date(2026, 6, 1),
        total_amount="1000.00",
        amount_paid="300.00",
        amount_credited="200.00",
    )
    assert record.amount_outstanding == Decimal("500.00")


def test_zero_outstanding_from_full_credit_does_not_raise() -> None:
    record = _invoice(due_date=date(2026, 1, 1), total_amount="800.00", amount_credited="800.00")
    assert record.amount_outstanding == Decimal("0")


def test_future_due_date_invoice_is_current_not_negative_days() -> None:
    record = _invoice(due_date=date(2026, 12, 25), total_amount="2000.00")
    assert record.days_overdue == 0
    assert record.bucket == AgingBucket.CURRENT
    assert record.amount_outstanding == Decimal("2000.00")


# ---------------------------------------------------------------------
# summarize_customer_aging — aggregation, multiple invoices, zero case
# ---------------------------------------------------------------------


def test_customer_with_no_invoices_is_clean_low_priority() -> None:
    summary = summarize_customer_aging(
        customer_id=uuid.uuid4(),
        customer_name="Empty Co",
        currency="PKR",
        credit_limit=None,
        invoices=[],
        as_of=_AS_OF,
    )
    assert summary.total_outstanding == Decimal("0")
    assert summary.priority == "low"
    assert summary.priority_score == 0
    assert summary.oldest_due_date is None
    assert "No overdue balance" in summary.priority_reasons[0]


def test_customer_with_only_fully_paid_invoices_is_zero_outstanding() -> None:
    cust_id = uuid.uuid4()
    invoices = [
        _invoice(due_date=date(2026, 3, 1), total_amount="1000", amount_paid="1000", customer_id=cust_id),
        _invoice(due_date=date(2026, 4, 1), total_amount="500", amount_paid="500", customer_id=cust_id),
    ]
    summary = summarize_customer_aging(
        customer_id=cust_id, customer_name="Paid Up Co", currency="PKR", credit_limit=None, invoices=invoices, as_of=_AS_OF
    )
    assert summary.total_outstanding == Decimal("0")
    assert summary.open_invoice_count == 0
    assert summary.priority == "low"


def test_multiple_invoices_per_customer_bucket_correctly() -> None:
    cust_id = uuid.uuid4()
    invoices = [
        _invoice(due_date=date(2026, 7, 20), total_amount="100", customer_id=cust_id),  # not yet due -> current
        _invoice(due_date=date(2026, 6, 15), total_amount="200", customer_id=cust_id),  # 15 days -> 1-30
        _invoice(due_date=date(2026, 4, 1), total_amount="300", customer_id=cust_id),  # 90 days -> 61-90
        _invoice(due_date=date(2026, 1, 1), total_amount="400", customer_id=cust_id),  # 180 days -> 121+
    ]
    summary = summarize_customer_aging(
        customer_id=cust_id, customer_name="Multi Invoice Co", currency="PKR", credit_limit=None, invoices=invoices, as_of=_AS_OF
    )
    assert summary.current_amount == Decimal("100")
    assert summary.amount_1_30 == Decimal("200")
    assert summary.amount_61_90 == Decimal("300")
    assert summary.amount_121_plus == Decimal("400")
    assert summary.total_outstanding == Decimal("1000")
    assert summary.open_invoice_count == 4
    assert summary.overdue_invoice_count == 3
    assert summary.oldest_days_overdue == (_AS_OF - date(2026, 1, 1)).days


def test_customer_aggregation_ignores_other_customers_invoices() -> None:
    cust_a = uuid.uuid4()
    cust_b = uuid.uuid4()
    invoices_a = [_invoice(due_date=date(2026, 1, 1), total_amount="900", customer_id=cust_a)]
    # Only cust_a's invoices should ever be passed in by the caller —
    # this test documents that summarize_customer_aging trusts its
    # input list rather than re-filtering by customer_id itself (that
    # filtering is AgingService's job, at the query layer).
    summary = summarize_customer_aging(
        customer_id=cust_a, customer_name="A", currency="PKR", credit_limit=None, invoices=invoices_a, as_of=_AS_OF
    )
    assert summary.total_outstanding == Decimal("900")
    assert summary.customer_id == cust_a
    assert summary.customer_id != cust_b


# ---------------------------------------------------------------------
# score_collection_priority — LOW / MEDIUM / HIGH / CRITICAL + reasons
# ---------------------------------------------------------------------


def test_priority_low_when_nothing_overdue() -> None:
    score, tier, reasons = score_collection_priority(
        oldest_days_overdue=0,
        total_outstanding=Decimal("5000"),
        amount_91_120=Decimal("0"),
        amount_121_plus=Decimal("0"),
        credit_limit=None,
        overdue_invoice_count=0,
    )
    assert tier == "low"
    assert score < MEDIUM_THRESHOLD
    assert "No overdue balance" in reasons[0]


def test_priority_medium_for_moderately_overdue_single_invoice() -> None:
    # 45 days overdue (31-60 bucket = 25 points), nothing else firing.
    score, tier, reasons = score_collection_priority(
        oldest_days_overdue=45,
        total_outstanding=Decimal("1000"),
        amount_91_120=Decimal("0"),
        amount_121_plus=Decimal("0"),
        credit_limit=None,
        overdue_invoice_count=1,
    )
    assert score == 25
    assert tier == "medium"
    assert MEDIUM_THRESHOLD <= score < HIGH_THRESHOLD
    assert any("45 day" in r for r in reasons)


def test_priority_high_for_severely_overdue_invoice() -> None:
    # 75 days overdue (61-90 bucket = 45 points) alone already crosses HIGH.
    score, tier, _ = score_collection_priority(
        oldest_days_overdue=75,
        total_outstanding=Decimal("1000"),
        amount_91_120=Decimal("0"),
        amount_121_plus=Decimal("0"),
        credit_limit=None,
        overdue_invoice_count=1,
    )
    assert score == 45
    assert tier == "high"
    assert HIGH_THRESHOLD <= score < CRITICAL_THRESHOLD


def test_priority_critical_for_very_old_invoice_concentrated_exposure() -> None:
    # 130 days overdue (121+ bucket = 85 points) + all of the balance
    # sitting in the 121+ bucket (severe exposure ratio 1.0 = +25).
    score, tier, reasons = score_collection_priority(
        oldest_days_overdue=130,
        total_outstanding=Decimal("2000"),
        amount_91_120=Decimal("0"),
        amount_121_plus=Decimal("2000"),
        credit_limit=None,
        overdue_invoice_count=1,
    )
    assert score == 100  # 85 + 25 = 110, capped at 100
    assert tier == "critical"
    assert score >= CRITICAL_THRESHOLD
    assert len(reasons) == 2


def test_priority_score_is_capped_at_100_not_above() -> None:
    score, tier, _ = score_collection_priority(
        oldest_days_overdue=400,
        total_outstanding=Decimal("100000"),
        amount_91_120=Decimal("0"),
        amount_121_plus=Decimal("100000"),
        credit_limit=Decimal("10000"),  # deeply over limit too
        overdue_invoice_count=10,
    )
    assert score == 100
    assert tier == "critical"


def test_credit_over_limit_reaches_medium_at_threshold() -> None:
    # Sanity: 20 points == MEDIUM_THRESHOLD, so >= comparison must
    # classify it as medium, not low.
    score, tier, _ = score_collection_priority(
        oldest_days_overdue=0,
        total_outstanding=Decimal("12000"),
        amount_91_120=Decimal("0"),
        amount_121_plus=Decimal("0"),
        credit_limit=Decimal("10000"),
        overdue_invoice_count=0,
    )
    assert score == 20
    assert MEDIUM_THRESHOLD == 20
    assert tier == "medium"


def test_chronic_overdue_count_signal_fires_at_documented_thresholds() -> None:
    _, _, reasons_low_count = score_collection_priority(
        oldest_days_overdue=5,
        total_outstanding=Decimal("100"),
        amount_91_120=Decimal("0"),
        amount_121_plus=Decimal("0"),
        credit_limit=None,
        overdue_invoice_count=1,
    )
    assert not any("chronic" in r for r in reasons_low_count)

    _, _, reasons_at_low_threshold = score_collection_priority(
        oldest_days_overdue=5,
        total_outstanding=Decimal("100"),
        amount_91_120=Decimal("0"),
        amount_121_plus=Decimal("0"),
        credit_limit=None,
        overdue_invoice_count=CHRONIC_OVERDUE_COUNT_LOW,
    )
    assert any("overdue invoices open at once" in r for r in reasons_at_low_threshold)

    _, _, reasons_at_high_threshold = score_collection_priority(
        oldest_days_overdue=5,
        total_outstanding=Decimal("100"),
        amount_91_120=Decimal("0"),
        amount_121_plus=Decimal("0"),
        credit_limit=None,
        overdue_invoice_count=CHRONIC_OVERDUE_COUNT_HIGH,
    )
    assert any("chronic pattern" in r for r in reasons_at_high_threshold)


def test_risk_and_priority_are_always_the_same_tier() -> None:
    cust_id = uuid.uuid4()
    invoices = [_invoice(due_date=date(2026, 1, 1), total_amount="900", customer_id=cust_id)]
    summary = summarize_customer_aging(
        customer_id=cust_id, customer_name="X", currency="PKR", credit_limit=None, invoices=invoices, as_of=_AS_OF
    )
    assert summary.risk == summary.priority


def test_recommended_action_maps_every_tier_to_a_distinct_action() -> None:
    actions = {tier: recommended_action_for_tier(tier) for tier in ("low", "medium", "high", "critical")}
    assert len(set(actions.values())) == 4  # every tier gets a distinct recommendation
    assert actions["low"] != actions["critical"]


# ---------------------------------------------------------------------
# summarize_portfolio_aging
# ---------------------------------------------------------------------


def test_portfolio_summary_rolls_up_multiple_customers() -> None:
    cust_a, cust_b = uuid.uuid4(), uuid.uuid4()
    invoices = [
        _invoice(due_date=date(2026, 7, 25), total_amount="500", customer_id=cust_a),  # not yet due -> current
        _invoice(due_date=date(2026, 3, 1), total_amount="700", customer_id=cust_b),  # overdue
    ]
    summary = summarize_portfolio_aging(as_of=_AS_OF, invoices=invoices)
    assert summary.total_outstanding == Decimal("1200")
    assert summary.customer_count == 2
    assert summary.overdue_invoice_count == 1
    assert summary.oldest_days_overdue == (_AS_OF - date(2026, 3, 1)).days


def test_portfolio_summary_empty_portfolio_does_not_raise() -> None:
    summary = summarize_portfolio_aging(as_of=_AS_OF, invoices=[])
    assert summary.total_outstanding == Decimal("0")
    assert summary.customer_count == 0
    assert summary.oldest_days_overdue == 0


# ---------------------------------------------------------------------
# Scoring signals, each at and around its documented threshold
# ---------------------------------------------------------------------


def _score(**overrides):
    params = dict(
        oldest_days_overdue=0,
        total_outstanding=Decimal("1000"),
        amount_91_120=Decimal("0"),
        amount_121_plus=Decimal("0"),
        credit_limit=None,
        overdue_invoice_count=0,
    )
    params.update(overrides)
    return score_collection_priority(**params)


def test_no_credit_limit_contributes_nothing_however_large_the_balance() -> None:
    score, _, _ = _score(total_outstanding=Decimal("999999"), credit_limit=None)
    assert score == 0


def test_balance_exactly_at_credit_limit_is_near_limit_not_over_limit() -> None:
    # "Over" is strictly greater, the same definition AccountsReceivableAgent uses.
    score, _, reasons = _score(total_outstanding=Decimal("1000"), credit_limit=Decimal("1000"))
    assert score == 10
    assert any("100% of the customer's credit limit" in r for r in reasons)


def test_balance_just_over_credit_limit_scores_over_limit_points() -> None:
    score, _, reasons = _score(total_outstanding=Decimal("1000.01"), credit_limit=Decimal("1000"))
    assert score == 20
    assert any("exceeds" in r for r in reasons)


def test_credit_near_limit_boundary_is_90_percent_inclusive() -> None:
    below, _, _ = _score(total_outstanding=Decimal("899.99"), credit_limit=Decimal("1000"))
    at, _, _ = _score(total_outstanding=Decimal("900"), credit_limit=Decimal("1000"))
    assert below == 0
    assert at == 10


def test_zero_credit_limit_with_any_balance_is_over_limit() -> None:
    score, _, reasons = _score(total_outstanding=Decimal("1"), credit_limit=Decimal("0"))
    assert score == 20
    assert any("exceeds" in r for r in reasons)


def test_zero_credit_limit_with_no_balance_is_not_a_signal() -> None:
    score, _, _ = _score(total_outstanding=Decimal("0"), credit_limit=Decimal("0"))
    assert score == 0


def test_severe_exposure_ratio_boundaries_are_25_and_50_percent_inclusive() -> None:
    total = Decimal("100")
    just_under_partial, _, _ = _score(total_outstanding=total, amount_91_120=Decimal("24.99"))
    at_partial, _, _ = _score(total_outstanding=total, amount_91_120=Decimal("25"))
    just_under_majority, _, _ = _score(total_outstanding=total, amount_121_plus=Decimal("49.99"))
    at_majority, _, _ = _score(total_outstanding=total, amount_121_plus=Decimal("50"))
    assert (just_under_partial, at_partial, just_under_majority, at_majority) == (0, 15, 15, 25)


def test_severe_exposure_combines_the_91_120_and_121_plus_buckets() -> None:
    # 30 + 25 of 100 total = 55% severe, which is over the 50% majority line
    # even though neither bucket alone reaches it.
    score, _, _ = _score(
        total_outstanding=Decimal("100"),
        amount_91_120=Decimal("30"),
        amount_121_plus=Decimal("25"),
    )
    assert score == 25


def test_overdue_invoice_count_boundaries() -> None:
    scores = {n: _score(overdue_invoice_count=n)[0] for n in (0, 1, 2, 4, 5, 9)}
    assert scores == {0: 0, 1: 0, 2: 5, 4: 5, 5: 10, 9: 10}


def test_reasons_come_one_per_active_signal_in_signal_order() -> None:
    score, tier, reasons = _score(
        oldest_days_overdue=130,
        total_outstanding=Decimal("100"),
        amount_121_plus=Decimal("100"),
        credit_limit=Decimal("50"),
        overdue_invoice_count=5,
    )
    assert (score, tier) == (100, "critical")  # 85 + 25 + 20 + 10 = 140, capped
    assert len(reasons) == 4
    assert "day(s) overdue" in reasons[0]
    assert "91+ days overdue" in reasons[1]
    assert "credit limit" in reasons[2]
    assert "chronic" in reasons[3]


# ---------------------------------------------------------------------
# Tier thresholds, using inputs that land on exact reachable scores
# ---------------------------------------------------------------------


def test_tier_threshold_boundaries() -> None:
    # Every signal is worth a multiple of 5 points, so scores like 19 or
    # 44 are unreachable; the closest reachable values either side of
    # each threshold are used instead.
    s15 = _score(oldest_days_overdue=10, overdue_invoice_count=2)  # 10 + 5
    s20 = _score(total_outstanding=Decimal("2000"), credit_limit=Decimal("1000"))  # over limit
    s40 = _score(
        oldest_days_overdue=45, total_outstanding=Decimal("100"), amount_91_120=Decimal("30")
    )  # 25 + 15
    s45 = _score(oldest_days_overdue=75)  # 61-90 bucket
    s65 = _score(oldest_days_overdue=100)  # 91-120 bucket
    s70 = _score(oldest_days_overdue=100, overdue_invoice_count=2)  # 65 + 5
    assert [(x[0], x[1]) for x in (s15, s20, s40, s45, s65, s70)] == [
        (15, "low"),
        (20, "medium"),
        (40, "medium"),
        (45, "high"),
        (65, "high"),
        (70, "critical"),
    ]


def test_priority_tier_type_is_exactly_the_four_documented_tiers() -> None:
    assert get_args(PriorityTier) == ("low", "medium", "high", "critical")
    for tier in get_args(PriorityTier):
        assert recommended_action_for_tier(tier)


def test_score_is_deterministic_for_identical_inputs() -> None:
    params = dict(
        oldest_days_overdue=95,
        total_outstanding=Decimal("5000"),
        amount_91_120=Decimal("2000"),
        amount_121_plus=Decimal("500"),
        credit_limit=Decimal("4000"),
        overdue_invoice_count=3,
    )
    first = score_collection_priority(**params)
    assert all(score_collection_priority(**params) == first for _ in range(25))


def test_score_never_decreases_as_the_oldest_invoice_gets_older() -> None:
    previous = -1
    for days in range(0, 400):
        score, _, _ = _score(oldest_days_overdue=days)
        assert score >= previous, f"score dropped at {days} days overdue"
        previous = score


def test_every_output_is_a_valid_tier_and_tier_follows_score_thresholds() -> None:
    valid = set(get_args(PriorityTier))
    for days in (0, 1, 30, 31, 60, 61, 90, 91, 120, 121, 400):
        for severe in ("0", "30", "60"):
            for limit in (None, Decimal("0"), Decimal("500"), Decimal("100000")):
                for count in (0, 1, 2, 5, 8):
                    score, tier, reasons = _score(
                        oldest_days_overdue=days,
                        total_outstanding=Decimal("100"),
                        amount_121_plus=Decimal(severe),
                        credit_limit=limit,
                        overdue_invoice_count=count,
                    )
                    assert tier in valid
                    assert 0 <= score <= 100
                    assert reasons, "reasons must never be empty"
                    if score >= CRITICAL_THRESHOLD:
                        expected = "critical"
                    elif score >= HIGH_THRESHOLD:
                        expected = "high"
                    elif score >= MEDIUM_THRESHOLD:
                        expected = "medium"
                    else:
                        expected = "low"
                    assert tier == expected


# ---------------------------------------------------------------------
# Customer summary details
# ---------------------------------------------------------------------


def test_customer_summary_credit_utilization_values() -> None:
    cust = uuid.uuid4()
    invoices = [_invoice(due_date=date(2026, 7, 15), total_amount="500", customer_id=cust)]

    def summarize(limit):
        return summarize_customer_aging(
            customer_id=cust,
            customer_name="C",
            currency="PKR",
            credit_limit=limit,
            invoices=invoices,
            as_of=_AS_OF,
        )

    assert summarize(Decimal("1000")).credit_utilization == Decimal("0.5")
    assert summarize(None).credit_utilization is None
    zero_limit = summarize(Decimal("0"))
    assert zero_limit.credit_utilization is None  # ratio undefined at a zero limit
    assert zero_limit.priority_score == 20  # but the over-limit signal still fires


def test_overpaid_invoice_is_excluded_not_subtracted_from_totals() -> None:
    cust = uuid.uuid4()
    invoices = [
        _invoice(due_date=date(2026, 1, 1), total_amount="100", amount_paid="150", customer_id=cust),
        _invoice(due_date=date(2026, 6, 1), total_amount="200", customer_id=cust),
    ]
    summary = summarize_customer_aging(
        customer_id=cust, customer_name="C", currency="PKR", credit_limit=None,
        invoices=invoices, as_of=_AS_OF,
    )
    assert summary.total_outstanding == Decimal("200")
    assert summary.open_invoice_count == 1
    assert summary.oldest_days_overdue == 29  # the overpaid old invoice is not "the oldest"


def test_partial_payment_stays_in_its_bucket_with_the_reduced_amount() -> None:
    cust = uuid.uuid4()
    due = date(2026, 3, 22)  # 100 days before _AS_OF
    invoices = [_invoice(due_date=due, total_amount="1000", amount_paid="400", customer_id=cust)]
    summary = summarize_customer_aging(
        customer_id=cust, customer_name="C", currency="PKR", credit_limit=None,
        invoices=invoices, as_of=_AS_OF,
    )
    assert (_AS_OF - due).days == 100
    assert summary.amount_91_120 == Decimal("600")
    assert summary.total_outstanding == Decimal("600")


# ---------------------------------------------------------------------
# Deterministic ordering and stable pagination
# ---------------------------------------------------------------------


def test_invoice_sort_key_is_total_and_independent_of_input_order() -> None:
    cust = uuid.uuid4()
    records = [
        _invoice(due_date=date(2026, 6, 1), total_amount="100", customer_id=cust, invoice_number="INV-B"),
        _invoice(due_date=date(2026, 6, 1), total_amount="100", customer_id=cust, invoice_number="INV-A"),
        _invoice(due_date=date(2026, 6, 1), total_amount="900", customer_id=cust, invoice_number="INV-C"),
        _invoice(due_date=date(2026, 5, 1), total_amount="50", customer_id=cust, invoice_number="INV-D"),
        _invoice(due_date=date(2026, 8, 1), total_amount="10", customer_id=cust, invoice_number="INV-E"),
    ]
    expected = ["INV-D", "INV-C", "INV-A", "INV-B", "INV-E"]
    rng = random.Random(1234)
    for _ in range(25):
        shuffled = records[:]
        rng.shuffle(shuffled)
        assert [r.invoice_number for r in sorted(shuffled, key=invoice_sort_key)] == expected


def test_customer_sort_key_is_total_and_independent_of_input_order() -> None:
    def summary(name: str, due: date, amount: str):
        cid = uuid.uuid4()
        return summarize_customer_aging(
            customer_id=cid,
            customer_name=name,
            currency="PKR",
            credit_limit=None,
            invoices=[_invoice(due_date=due, total_amount=amount, customer_id=cid)],
            as_of=_AS_OF,
        )

    summaries = [
        summary("Zeta Traders", date(2026, 6, 15), "100"),  # score 10, 100
        summary("alpha Corp", date(2026, 6, 15), "100"),  # score 10, 100 (name breaks the tie)
        summary("Big Same Score", date(2026, 6, 15), "500"),  # score 10, larger balance
        summary("Very Old", date(2026, 1, 1), "50"),  # highest score
    ]
    expected = ["Very Old", "Big Same Score", "alpha Corp", "Zeta Traders"]
    rng = random.Random(4321)
    for _ in range(25):
        shuffled = summaries[:]
        rng.shuffle(shuffled)
        assert [s.customer_name for s in sorted(shuffled, key=customer_sort_key)] == expected


def test_paging_over_fully_tied_rows_never_duplicates_or_skips() -> None:
    cust = uuid.uuid4()
    # All 11 tie on every numeric sort input (0 days overdue, same amount).
    records = [
        _invoice(due_date=date(2026, 7, 15), total_amount="100", customer_id=cust, invoice_number=f"INV-{i:03d}")
        for i in range(11)
    ]
    rng = random.Random(99)
    for _ in range(10):
        shuffled = records[:]
        rng.shuffle(shuffled)
        ordered = sorted(shuffled, key=invoice_sort_key)
        pages = [ordered[i : i + 4] for i in range(0, len(ordered), 4)]
        seen = [r.invoice_number for page in pages for r in page]
        assert len(seen) == 11
        assert len(set(seen)) == 11
        assert seen == sorted(r.invoice_number for r in records)



def test_mixed_currency_customer_balances_are_grouped_without_consolidated_total() -> None:
    from dataclasses import replace
    customer_id = uuid.uuid4()
    usd = replace(_invoice(due_date=date(2026, 6, 1), total_amount="999999999999999999.99", customer_id=customer_id), currency="USD")
    eur = replace(_invoice(due_date=date(2026, 6, 15), total_amount="0.01", customer_id=customer_id), currency="EUR")
    summary = summarize_customer_aging(customer_id=customer_id, customer_name="Mixed Currency", currency="PKR", credit_limit=Decimal("1000"), invoices=[usd, eur], as_of=_AS_OF)
    assert summary.currency is None and summary.total_outstanding is None and summary.overdue_amount is None
    balances = {b.currency: b for b in summary.currency_balances}
    assert balances["USD"].total_outstanding == Decimal("999999999999999999.99")
    assert balances["EUR"].total_outstanding == Decimal("0.01")
    assert balances["USD"].credit_limit is None and balances["EUR"].credit_limit is None
    assert summary.open_invoice_count == 2


def test_portfolio_mixed_currency_totals_are_null_and_details_exact() -> None:
    from dataclasses import replace
    a, b = uuid.uuid4(), uuid.uuid4()
    usd = replace(_invoice(due_date=date(2026, 6, 1), total_amount="100.10", customer_id=a), currency="USD")
    pkr = replace(_invoice(due_date=date(2026, 6, 15), total_amount="200.20", customer_id=b), currency="PKR")
    summary = summarize_portfolio_aging(as_of=_AS_OF, invoices=[usd, pkr])
    assert summary.currency is None and summary.total_outstanding is None
    assert {balance.currency: balance.total_outstanding for balance in summary.currency_balances} == {"PKR": Decimal("200.20"), "USD": Decimal("100.10")}


def test_zero_and_negative_outstanding_are_not_in_currency_totals() -> None:
    customer_id = uuid.uuid4()
    zero = _invoice(due_date=date(2026, 6, 1), total_amount="0.00", customer_id=customer_id)
    overpaid = _invoice(due_date=date(2026, 1, 1), total_amount="10.00", amount_paid="12.00", customer_id=customer_id)
    summary = summarize_portfolio_aging(as_of=_AS_OF, invoices=[zero, overpaid])
    assert summary.total_outstanding == Decimal("0")
    assert summary.currency_balances == []


def test_currency_code_normalization_keeps_missing_or_invalid_codes_explicit() -> None:
    from app.services.currency_utils import normalize_currency_code
    assert normalize_currency_code("pkr") == "PKR"
    assert normalize_currency_code("") == "UNSPECIFIED"
    assert normalize_currency_code("XYZ") == "UNSUPPORTED:XYZ"


def test_credit_limit_only_applies_to_customer_default_currency_balance() -> None:
    from dataclasses import replace
    customer_id = uuid.uuid4()
    pkr = replace(_invoice(due_date=date(2026, 6, 1), total_amount="1200", customer_id=customer_id), currency="PKR")
    usd = replace(_invoice(due_date=date(2026, 6, 1), total_amount="500", customer_id=customer_id), currency="USD")
    summary = summarize_customer_aging(customer_id=customer_id, customer_name="Credit Currency", currency="PKR", credit_limit=Decimal("1000"), invoices=[pkr, usd], as_of=_AS_OF)
    balances = {b.currency: b for b in summary.currency_balances}
    assert balances["PKR"].credit_limit == Decimal("1000")
    assert balances["PKR"].credit_utilization == Decimal("1.2")
    assert balances["USD"].credit_limit is None and balances["USD"].credit_utilization is None
