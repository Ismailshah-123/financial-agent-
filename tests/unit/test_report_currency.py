"""Unit tests for the single-currency policy of the General Ledger reports.

The reports must never add amounts that are denominated in different
currencies, and the platform has no authoritative FX-rate model, so the
service either reports one currency or refuses to guess.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ValidationError
from app.services.report_currency import resolve_report_currency


def test_single_posted_currency_is_selected_automatically() -> None:
    assert resolve_report_currency(["USD"], None) == "USD"


def test_duplicates_and_case_do_not_create_ambiguity() -> None:
    assert resolve_report_currency(["usd", "USD", " USD "], None) == "USD"


def test_empty_ledger_window_has_no_currency() -> None:
    assert resolve_report_currency([], None) is None


def test_multiple_currencies_without_a_choice_are_refused() -> None:
    with pytest.raises(ValidationError) as excinfo:
        resolve_report_currency(["USD", "PKR"], None)
    assert excinfo.value.details["available_currencies"] == ["PKR", "USD"]
    assert "never combined" in excinfo.value.message


def test_explicit_currency_wins_even_when_ledger_is_mixed() -> None:
    assert resolve_report_currency(["USD", "PKR", "EUR"], "pkr") == "PKR"


def test_explicit_currency_with_no_postings_is_allowed() -> None:
    # An empty report for a currency nobody posted in is truthful; it is not an error.
    assert resolve_report_currency(["USD"], "EUR") == "EUR"


@pytest.mark.parametrize("bad", ["", "US", "USDX", "U5D", "12 ", "€€€"])
def test_malformed_currency_codes_are_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        resolve_report_currency(["USD"], bad)


def test_falsy_entries_in_available_are_ignored() -> None:
    assert resolve_report_currency(["", "USD", None], None) == "USD"  # type: ignore[list-item]
