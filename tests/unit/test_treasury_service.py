"""
Unit tests for TreasuryService's pure logic: _walk_events (the
chronological running-balance walk) and assess_liquidity_risk. Both
take plain dataclasses/Decimal values, no DB session, no event loop.

forecast_cash_flow() itself (which adds the DB queries for open AR
invoices and scheduled payments) is exercised by
tests/integration/test_treasury.py instead — same split as every other
agent's test files this session.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.treasury_service import (
    HIGH_RISK_BUFFER_RATIO,
    MEDIUM_RISK_BUFFER_RATIO,
    CashFlowEvent,
    CashFlowForecast,
    _walk_events,
    assess_liquidity_risk,
)


def _event(day: int, amount: str, source_type: str = "ar_invoice_due") -> CashFlowEvent:
    return CashFlowEvent(
        event_date=date(2026, 1, day),
        amount=Decimal(amount),
        source_type=source_type,
        source_id="x",
        description="test event",
    )


# ---- _walk_events ----


def test_walk_events_empty_holds_balance_flat() -> None:
    ending, lowest, lowest_date = _walk_events(starting_balance=Decimal("1000"), events=[])
    assert ending == Decimal("1000")
    assert lowest == Decimal("1000")
    assert lowest_date is None


def test_walk_events_single_inflow_raises_balance_no_dip() -> None:
    events = [_event(5, "500")]
    ending, lowest, lowest_date = _walk_events(starting_balance=Decimal("1000"), events=events)
    assert ending == Decimal("1500")
    assert lowest == Decimal("1000")  # never dips below the start
    assert lowest_date is None


def test_walk_events_single_outflow_dips_and_ends_there() -> None:
    events = [_event(5, "-300")]
    ending, lowest, lowest_date = _walk_events(starting_balance=Decimal("1000"), events=events)
    assert ending == Decimal("700")
    assert lowest == Decimal("700")
    assert lowest_date == date(2026, 1, 5)


def test_walk_events_dip_then_recover_reports_the_dip_not_the_end() -> None:
    # Balance dips to 200 on day 5, then recovers to 900 on day 10 —
    # the lowest point (200 on day 5) must be reported, not the
    # higher ending balance.
    events = [_event(5, "-800"), _event(10, "700")]
    ending, lowest, lowest_date = _walk_events(starting_balance=Decimal("1000"), events=events)
    assert ending == Decimal("900")
    assert lowest == Decimal("200")
    assert lowest_date == date(2026, 1, 5)


def test_walk_events_multiple_new_lows_reports_the_final_lowest() -> None:
    events = [_event(3, "-200"), _event(6, "-500"), _event(9, "100")]
    ending, lowest, lowest_date = _walk_events(starting_balance=Decimal("1000"), events=events)
    assert ending == Decimal("400")
    assert lowest == Decimal("300")  # 1000 - 200 - 500
    assert lowest_date == date(2026, 1, 6)


def test_walk_events_goes_negative() -> None:
    events = [_event(5, "-1500")]
    ending, lowest, lowest_date = _walk_events(starting_balance=Decimal("1000"), events=events)
    assert lowest == Decimal("-500")
    assert lowest_date == date(2026, 1, 5)


# ---- assess_liquidity_risk ----


def _forecast(starting: str, lowest: str) -> CashFlowForecast:
    return CashFlowForecast(
        as_of=date.today(),
        horizon_days=30,
        starting_balance=Decimal(starting),
        ending_balance=Decimal(lowest),
        lowest_balance=Decimal(lowest),
        lowest_balance_date=date.today() if Decimal(lowest) != Decimal(starting) else None,
    )


def test_negative_lowest_is_critical() -> None:
    assert assess_liquidity_risk(_forecast("10000", "-1")) == "critical"


def test_lowest_below_high_threshold_is_high() -> None:
    # Just under the 10% threshold.
    ratio = HIGH_RISK_BUFFER_RATIO - Decimal("0.01")
    lowest = (Decimal("10000") * ratio).quantize(Decimal("0.01"))
    assert assess_liquidity_risk(_forecast("10000", str(lowest))) == "high"


def test_lowest_below_medium_threshold_is_medium() -> None:
    ratio = MEDIUM_RISK_BUFFER_RATIO - Decimal("0.01")
    lowest = (Decimal("10000") * ratio).quantize(Decimal("0.01"))
    assert assess_liquidity_risk(_forecast("10000", str(lowest))) == "medium"


def test_lowest_comfortably_above_thresholds_is_low() -> None:
    assert assess_liquidity_risk(_forecast("10000", "9000")) == "low"


def test_zero_starting_balance_is_always_high_not_critical_or_medium() -> None:
    # lowest_balance can never exceed starting_balance (by construction
    # of _walk_events — see that function's docstring), so reaching
    # here with starting_balance == 0 always means lowest_balance == 0
    # too. Already being at zero cash is inherently high severity.
    assert assess_liquidity_risk(_forecast("0", "0")) == "high"


def test_zero_starting_balance_that_goes_negative_is_critical() -> None:
    assert assess_liquidity_risk(_forecast("0", "-100")) == "critical"
