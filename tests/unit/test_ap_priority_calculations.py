"""
Unit tests for app.services.ap_priority_calculations. Same convention
as tests/unit/test_aging_calculations.py: plain functions, plain
asserts, no DB, no fixtures — genuinely executable with nothing but the
standard library, verified by actually running this file with a
stdlib-only runner (no pytest) during the session that added it.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import get_args

from app.services.ap_priority_calculations import (
    CRITICAL_THRESHOLD,
    HIGH_THRESHOLD,
    MEDIUM_THRESHOLD,
    DueBucket,
    PaymentPriorityStatus,
    PriorityTier,
    bucket_for_days_until_due,
    build_reason,
    compute_days_until_due,
    compute_payment_obligation,
    obligation_sort_key,
    score_payment_priority,
    summarize_ap_priority,
    summarize_vendor_exposure,
    vendor_sort_key,
)

_AS_OF = date(2026, 6, 30)


def _obligation(
    *,
    status: PaymentPriorityStatus,
    due_date: date,
    amount: str = "1000",
    vendor_id: uuid.UUID | None = None,
    invoice_number: str = "INV-1",
    status_detail: str | None = None,
    scheduled_date: date | None = None,
    executed_date: date | None = None,
    currency: str = "PKR",
):
    return compute_payment_obligation(
        invoice_id=uuid.uuid4(),
        invoice_number=invoice_number,
        vendor_id=vendor_id or uuid.uuid4(),
        vendor_name="Test Vendor",
        amount=Decimal(amount),
        currency=currency,
        due_date=due_date,
        as_of=_AS_OF,
        status=status,
        status_detail=status_detail,
        scheduled_date=scheduled_date,
        executed_date=executed_date,
    )


# ---------------------------------------------------------------------
# compute_days_until_due / bucket_for_days_until_due
# ---------------------------------------------------------------------


def test_due_date_in_the_past_is_negative_days_until_due() -> None:
    assert compute_days_until_due(due_date=date(2026, 6, 20), as_of=_AS_OF) == -10


def test_due_today_is_zero_days_until_due() -> None:
    assert compute_days_until_due(due_date=_AS_OF, as_of=_AS_OF) == 0


def test_one_day_overdue_buckets_as_overdue() -> None:
    assert bucket_for_days_until_due(-1) == DueBucket.OVERDUE


def test_due_today_buckets_as_due_today() -> None:
    assert bucket_for_days_until_due(0) == DueBucket.DUE_TODAY


def test_due_within_7_boundary_is_inclusive() -> None:
    assert bucket_for_days_until_due(7) == DueBucket.DUE_WITHIN_7
    assert bucket_for_days_until_due(8) == DueBucket.DUE_WITHIN_30


def test_due_within_30_boundary_is_inclusive() -> None:
    assert bucket_for_days_until_due(30) == DueBucket.DUE_WITHIN_30
    assert bucket_for_days_until_due(31) == DueBucket.DUE_LATER


def test_far_future_due_date_is_due_later() -> None:
    assert bucket_for_days_until_due(400) == DueBucket.DUE_LATER


# ---------------------------------------------------------------------
# score_payment_priority: every status, overdue scaling boundaries
# ---------------------------------------------------------------------


def test_executed_has_no_score_or_tier() -> None:
    score, tier = score_payment_priority(
        status=PaymentPriorityStatus.EXECUTED, due_bucket=DueBucket.NOT_APPLICABLE, days_until_due=0
    )
    assert (score, tier) == (None, None)


def test_ready_to_schedule_far_out_is_low() -> None:
    score, tier = score_payment_priority(
        status=PaymentPriorityStatus.READY_TO_SCHEDULE,
        due_bucket=DueBucket.DUE_LATER,
        days_until_due=60,
    )
    assert score == 0
    assert tier == "low"


def test_ready_to_schedule_due_today_is_medium() -> None:
    score, tier = score_payment_priority(
        status=PaymentPriorityStatus.READY_TO_SCHEDULE,
        due_bucket=DueBucket.DUE_TODAY,
        days_until_due=0,
    )
    assert score == 15
    assert tier == "medium"
    assert MEDIUM_THRESHOLD == 15  # pins the exact boundary this test relies on


def test_overdue_scaling_1_to_7_8_to_30_31_plus() -> None:
    cases = [(-1, 20), (-7, 20), (-8, 45), (-30, 45), (-31, 70), (-400, 70)]
    for days_until_due, expected_points in cases:
        score, _ = score_payment_priority(
            status=PaymentPriorityStatus.READY_TO_SCHEDULE,
            due_bucket=DueBucket.OVERDUE,
            days_until_due=days_until_due,
        )
        assert score == expected_points, f"{days_until_due} days -> expected {expected_points}, got {score}"


def test_awaiting_approval_even_when_not_due_yet_is_at_least_medium() -> None:
    score, tier = score_payment_priority(
        status=PaymentPriorityStatus.AWAITING_APPROVAL,
        due_bucket=DueBucket.DUE_LATER,
        days_until_due=90,
    )
    assert score == 20
    assert tier == "medium"


def test_blocked_not_yet_due_is_medium_blocked_and_overdue_is_higher() -> None:
    not_due_score, not_due_tier = score_payment_priority(
        status=PaymentPriorityStatus.BLOCKED, due_bucket=DueBucket.DUE_LATER, days_until_due=90
    )
    overdue_score, overdue_tier = score_payment_priority(
        status=PaymentPriorityStatus.BLOCKED, due_bucket=DueBucket.OVERDUE, days_until_due=-10
    )
    assert not_due_score == 35
    assert not_due_tier == "medium"
    assert overdue_score == 35 + 45  # 8-30 day overdue bracket = 80, capped under 100
    assert overdue_tier == "critical"  # 80 >= CRITICAL_THRESHOLD (70)
    assert overdue_score > not_due_score  # blocked AND overdue must outrank blocked alone


def test_payment_failed_is_high_priority_even_with_a_distant_due_date() -> None:
    score, tier = score_payment_priority(
        status=PaymentPriorityStatus.PAYMENT_FAILED, due_bucket=DueBucket.DUE_LATER, days_until_due=90
    )
    assert score == 50
    assert tier == "high"


def test_payment_failed_and_severely_overdue_is_critical_capped_at_100() -> None:
    score, tier = score_payment_priority(
        status=PaymentPriorityStatus.PAYMENT_FAILED, due_bucket=DueBucket.OVERDUE, days_until_due=-45
    )
    assert score == 100  # 50 + 70 = 120, capped
    assert tier == "critical"


def test_scheduled_with_no_overdue_signal_is_low() -> None:
    score, tier = score_payment_priority(
        status=PaymentPriorityStatus.SCHEDULED, due_bucket=DueBucket.DUE_WITHIN_30, days_until_due=15
    )
    assert score == 0
    assert tier == "low"


def test_every_status_produces_a_valid_result_shape() -> None:
    for status in PaymentPriorityStatus:
        for bucket, days in (
            (DueBucket.OVERDUE, -5), (DueBucket.DUE_TODAY, 0), (DueBucket.DUE_WITHIN_7, 3),
            (DueBucket.DUE_WITHIN_30, 20), (DueBucket.DUE_LATER, 60),
        ):
            score, tier = score_payment_priority(status=status, due_bucket=bucket, days_until_due=days)
            if status == PaymentPriorityStatus.EXECUTED:
                assert (score, tier) == (None, None)
            else:
                assert score is not None and 0 <= score <= 100
                assert tier in get_args(PriorityTier)
                if score >= CRITICAL_THRESHOLD:
                    assert tier == "critical"
                elif score >= HIGH_THRESHOLD:
                    assert tier == "high"
                elif score >= MEDIUM_THRESHOLD:
                    assert tier == "medium"
                else:
                    assert tier == "low"


# ---------------------------------------------------------------------
# build_reason
# ---------------------------------------------------------------------


def test_reason_includes_status_detail_when_given() -> None:
    reason = build_reason(
        status=PaymentPriorityStatus.BLOCKED,
        due_bucket=DueBucket.DUE_LATER,
        days_until_due=60,
        detail="price mismatch",
    )
    assert "price mismatch" in reason
    assert "Blocked by a 3-way match issue" in reason


def test_reason_for_ready_to_schedule_states_days_overdue() -> None:
    reason = build_reason(
        status=PaymentPriorityStatus.READY_TO_SCHEDULE,
        due_bucket=DueBucket.OVERDUE,
        days_until_due=-12,
        detail=None,
    )
    assert "12 day(s) overdue" in reason


def test_reason_for_blocked_does_not_append_due_timing_language() -> None:
    # Only READY_TO_SCHEDULE/SCHEDULED get the "N days overdue"/"due
    # today" suffix (see build_reason) — a blocked invoice's problem is
    # the match failure, not timing, even if it's also overdue.
    reason = build_reason(
        status=PaymentPriorityStatus.BLOCKED, due_bucket=DueBucket.OVERDUE, days_until_due=-12, detail=None
    )
    assert "overdue" not in reason.lower()


# ---------------------------------------------------------------------
# compute_payment_obligation end to end
# ---------------------------------------------------------------------


def test_compute_payment_obligation_executed_has_not_applicable_bucket() -> None:
    obligation = _obligation(status=PaymentPriorityStatus.EXECUTED, due_date=date(2026, 1, 1))
    assert obligation.due_bucket == DueBucket.NOT_APPLICABLE
    assert obligation.priority is None
    assert obligation.priority_score is None


def test_compute_payment_obligation_carries_scheduled_and_executed_dates() -> None:
    obligation = _obligation(
        status=PaymentPriorityStatus.SCHEDULED,
        due_date=date(2026, 7, 5),
        scheduled_date=date(2026, 7, 1),
    )
    assert obligation.scheduled_date == date(2026, 7, 1)
    assert obligation.executed_date is None


# ---------------------------------------------------------------------
# summarize_vendor_exposure
# ---------------------------------------------------------------------


def test_vendor_with_no_obligations_has_zero_exposure() -> None:
    summary = summarize_vendor_exposure(
        vendor_id=uuid.uuid4(), vendor_name="Empty Vendor", currency="PKR", obligations=[]
    )
    assert summary.total_exposure == Decimal("0")
    assert summary.open_invoice_count == 0
    assert summary.highest_priority == "low"


def test_vendor_exposure_excludes_executed_from_totals() -> None:
    vid = uuid.uuid4()
    obligations = [
        _obligation(status=PaymentPriorityStatus.EXECUTED, due_date=date(2026, 1, 1), amount="500", vendor_id=vid),
        _obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 7, 20), amount="300", vendor_id=vid),
    ]
    summary = summarize_vendor_exposure(vendor_id=vid, vendor_name="V", currency="PKR", obligations=obligations)
    assert summary.total_exposure == Decimal("300")
    assert summary.open_invoice_count == 1


def test_vendor_exposure_counts_overdue_amount_and_status_buckets() -> None:
    vid = uuid.uuid4()
    obligations = [
        _obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 5, 1), amount="400", vendor_id=vid),  # overdue
        _obligation(status=PaymentPriorityStatus.BLOCKED, due_date=date(2026, 7, 20), amount="250", vendor_id=vid),
        _obligation(status=PaymentPriorityStatus.PAYMENT_FAILED, due_date=date(2026, 6, 1), amount="900", vendor_id=vid),  # overdue
        _obligation(status=PaymentPriorityStatus.AWAITING_APPROVAL, due_date=date(2026, 8, 1), amount="100", vendor_id=vid),
    ]
    summary = summarize_vendor_exposure(vendor_id=vid, vendor_name="V", currency="PKR", obligations=obligations)
    assert summary.total_exposure == Decimal("1650")
    assert summary.open_invoice_count == 4
    assert summary.overdue_invoice_count == 2
    assert summary.overdue_amount == Decimal("1300")
    assert summary.blocked_count == 1
    assert summary.payment_failed_count == 1
    assert summary.awaiting_approval_count == 1
    assert summary.highest_priority == "critical"  # the payment_failed + overdue row


def test_vendor_exposure_ignores_other_vendors_obligations() -> None:
    vid_a, vid_b = uuid.uuid4(), uuid.uuid4()
    obligations_a = [_obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 7, 10), amount="700", vendor_id=vid_a)]
    summary = summarize_vendor_exposure(vendor_id=vid_a, vendor_name="A", currency="PKR", obligations=obligations_a)
    assert summary.total_exposure == Decimal("700")
    assert summary.vendor_id == vid_a
    assert summary.vendor_id != vid_b


# ---------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------


def test_obligation_sort_key_puts_executed_last_and_is_order_independent() -> None:
    items = [
        _obligation(status=PaymentPriorityStatus.EXECUTED, due_date=date(2026, 1, 1), amount="999", invoice_number="INV-EXEC"),
        _obligation(status=PaymentPriorityStatus.PAYMENT_FAILED, due_date=date(2026, 5, 1), amount="100", invoice_number="INV-FAILED"),
        _obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 7, 25), amount="100", invoice_number="INV-NOT-DUE"),
    ]
    expected = ["INV-FAILED", "INV-NOT-DUE", "INV-EXEC"]
    rng = random.Random(7)
    for _ in range(15):
        shuffled = items[:]
        rng.shuffle(shuffled)
        assert [o.invoice_number for o in sorted(shuffled, key=obligation_sort_key)] == expected


def test_vendor_sort_key_highest_priority_first_ties_by_exposure_then_name() -> None:
    def vendor(name, amount, status, due):
        vid = uuid.uuid4()
        return summarize_vendor_exposure(
            vendor_id=vid, vendor_name=name, currency="PKR",
            obligations=[_obligation(status=status, due_date=due, amount=amount, vendor_id=vid)],
        )

    vendors = [
        vendor("Zed Co", "100", PaymentPriorityStatus.READY_TO_SCHEDULE, date(2026, 7, 20)),  # low
        vendor("Acme Co", "100", PaymentPriorityStatus.READY_TO_SCHEDULE, date(2026, 7, 20)),  # low, ties with Zed -> name breaks tie
        vendor("Big Low Co", "500", PaymentPriorityStatus.READY_TO_SCHEDULE, date(2026, 7, 20)),  # low, bigger exposure
        vendor("Critical Co", "50", PaymentPriorityStatus.PAYMENT_FAILED, date(2026, 4, 1)),  # critical
    ]
    expected = ["Critical Co", "Big Low Co", "Acme Co", "Zed Co"]
    rng = random.Random(11)
    for _ in range(15):
        shuffled = vendors[:]
        rng.shuffle(shuffled)
        assert [v.vendor_name for v in sorted(shuffled, key=vendor_sort_key)] == expected



def test_vendor_exposure_never_combines_different_document_currencies() -> None:
    vendor_id = uuid.uuid4()
    obligations = [
        _obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 6, 25), amount="100.10", vendor_id=vendor_id, currency="USD"),
        _obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 6, 20), amount="200.20", vendor_id=vendor_id, currency="EUR"),
    ]
    summary = summarize_vendor_exposure(vendor_id=vendor_id, vendor_name="Mixed Currency Vendor", currency="PKR", obligations=obligations)
    assert summary.currency is None
    assert summary.total_exposure is None
    assert summary.overdue_amount is None
    assert {b.currency: b.total_exposure for b in summary.currency_balances} == {"EUR": Decimal("200.20"), "USD": Decimal("100.10")}


def test_vendor_exposure_large_decimal_preserves_single_currency_total() -> None:
    vendor_id = uuid.uuid4()
    obligations = [
        _obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 6, 25), amount="0.01", vendor_id=vendor_id, currency="USD"),
        _obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 6, 20), amount="999999999999999999.99", vendor_id=vendor_id, currency="USD"),
    ]
    summary = summarize_vendor_exposure(vendor_id=vendor_id, vendor_name="Single Currency", currency="PKR", obligations=obligations)
    assert summary.currency == "USD"
    assert summary.total_exposure == Decimal("1000000000000000000.00")


def test_ap_summary_groups_status_and_totals_by_currency() -> None:
    obligations = [
        _obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 6, 25), amount="10.10", currency="USD"),
        _obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 6, 20), amount="20.20", currency="EUR"),
    ]
    summary = summarize_ap_priority(as_of=_AS_OF, obligations=obligations)
    assert summary["currency"] is None
    assert summary["total_payable"] is None
    assert summary["overdue_amount"] is None
    assert summary["by_status_amount"] == {}
    assert {b.currency: b.total_payable for b in summary["currency_balances"]} == {"EUR": Decimal("20.20"), "USD": Decimal("10.10")}


def test_ap_summary_keeps_precise_single_currency_totals() -> None:
    obligations = [
        _obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 6, 25), amount="0.01", currency="USD"),
        _obligation(status=PaymentPriorityStatus.READY_TO_SCHEDULE, due_date=date(2026, 6, 20), amount="999999999999999999.99", currency="USD"),
    ]
    summary = summarize_ap_priority(as_of=_AS_OF, obligations=obligations)
    assert summary["currency"] == "USD"
    assert summary["total_payable"] == Decimal("1000000000000000000.00")
