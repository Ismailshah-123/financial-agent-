"""
Unit tests for BudgetService's pure logic: _elapsed_fraction and
assess_variance_risk. Both take plain values/dataclasses, no DB
session, no event loop.

compute_variance() itself (which adds the chart-of-accounts lookup and
the period-scoped account balance query) is exercised by
tests/integration/test_budget_planning.py instead — same split as
every other agent's test files this session.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.models.budget import Budget
from app.services.budget_service import (
    CRITICAL_VARIANCE_RATIO,
    HIGH_VARIANCE_RATIO,
    BudgetVariance,
    _elapsed_fraction,
    assess_variance_risk,
)


# ---- _elapsed_fraction ----


def test_elapsed_fraction_before_period_start_is_zero() -> None:
    result = _elapsed_fraction(
        as_of=date(2025, 12, 15), period_start=date(2026, 1, 1), period_end=date(2026, 1, 31)
    )
    assert result == Decimal("0")


def test_elapsed_fraction_at_period_end_is_one() -> None:
    result = _elapsed_fraction(
        as_of=date(2026, 1, 31), period_start=date(2026, 1, 1), period_end=date(2026, 1, 31)
    )
    assert result == Decimal("1")


def test_elapsed_fraction_after_period_end_is_clamped_to_one() -> None:
    result = _elapsed_fraction(
        as_of=date(2026, 6, 1), period_start=date(2026, 1, 1), period_end=date(2026, 1, 31)
    )
    assert result == Decimal("1")


def test_elapsed_fraction_at_period_start_is_zero() -> None:
    result = _elapsed_fraction(
        as_of=date(2026, 1, 1), period_start=date(2026, 1, 1), period_end=date(2026, 1, 31)
    )
    assert result == Decimal("0")


def test_elapsed_fraction_midpoint() -> None:
    result = _elapsed_fraction(
        as_of=date(2026, 1, 16), period_start=date(2026, 1, 1), period_end=date(2026, 1, 31)
    )
    # 15 days elapsed of 30 total = 0.5
    assert result == Decimal("0.5")


def test_elapsed_fraction_zero_length_period_is_fully_elapsed() -> None:
    result = _elapsed_fraction(
        as_of=date(2026, 1, 1), period_start=date(2026, 1, 1), period_end=date(2026, 1, 1)
    )
    assert result == Decimal("1")


# ---- assess_variance_risk ----


def _variance(ratio: str, *, is_meaningful: bool = True) -> BudgetVariance:
    budget = Budget(
        name="Test Budget",
        account_code="5000-EXP",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        budgeted_amount=Decimal("10000"),
        currency="USD",
    )
    return BudgetVariance(
        budget=budget,
        account_type="expense",
        actual_amount=Decimal("0"),
        elapsed_fraction=Decimal("0.5"),
        expected_amount_at_pace=Decimal("5000"),
        variance_ratio=Decimal(ratio),
        is_meaningful=is_meaningful,
    )


def test_negative_ratio_favorable_is_low() -> None:
    assert assess_variance_risk(_variance("-0.10")) == "low"


def test_zero_ratio_on_pace_is_low() -> None:
    assert assess_variance_risk(_variance("0")) == "low"


def test_small_positive_ratio_is_medium() -> None:
    assert assess_variance_risk(_variance("0.05")) == "medium"


def test_ratio_just_under_high_threshold_is_medium() -> None:
    just_under = HIGH_VARIANCE_RATIO - Decimal("0.001")
    assert assess_variance_risk(_variance(str(just_under))) == "medium"


def test_ratio_at_high_threshold_is_high() -> None:
    assert assess_variance_risk(_variance(str(HIGH_VARIANCE_RATIO))) == "high"


def test_ratio_just_under_critical_threshold_is_high() -> None:
    just_under = CRITICAL_VARIANCE_RATIO - Decimal("0.001")
    assert assess_variance_risk(_variance(str(just_under))) == "high"


def test_ratio_at_critical_threshold_is_critical() -> None:
    assert assess_variance_risk(_variance(str(CRITICAL_VARIANCE_RATIO))) == "critical"


def test_very_large_ratio_is_critical() -> None:
    assert assess_variance_risk(_variance("2.5")) == "critical"


def test_not_meaningful_is_always_low_regardless_of_ratio() -> None:
    # e.g. a budget against an ASSET/LIABILITY/EQUITY account — the
    # ratio field is unused/zero in this case, but even if it weren't,
    # is_meaningful=False should short-circuit to low.
    assert assess_variance_risk(_variance("5.0", is_meaningful=False)) == "low"
