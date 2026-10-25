"""
Unit tests for app.services.financial_reporting_service.compute_account_balance
— the pure calculation at the core of every report (Trial Balance, P&L,
Balance Sheet). No DB needed; the DB-touching aggregation
(_aggregate_by_account) is exercised separately by an integration test
against real posted journal entries.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.financial_reporting_service import compute_account_balance


def test_debit_normal_account_balance_is_debit_minus_credit() -> None:
    balance = compute_account_balance(
        total_debit=Decimal("1000"), total_credit=Decimal("300"), normal_side="debit"
    )
    assert balance == Decimal("700")


def test_credit_normal_account_balance_is_credit_minus_debit() -> None:
    balance = compute_account_balance(
        total_debit=Decimal("300"), total_credit=Decimal("1000"), normal_side="credit"
    )
    assert balance == Decimal("700")


def test_debit_normal_account_with_more_credits_than_debits_is_negative() -> None:
    """A debit-normal account (e.g. Cash) showing a negative balance
    signals something is off — more credited out than ever debited in.
    The function should surface that as a negative number, not clamp
    it, since hiding the sign would hide a real data problem."""
    balance = compute_account_balance(
        total_debit=Decimal("100"), total_credit=Decimal("500"), normal_side="debit"
    )
    assert balance == Decimal("-400")


def test_zero_activity_account_has_zero_balance() -> None:
    balance = compute_account_balance(
        total_debit=Decimal("0"), total_credit=Decimal("0"), normal_side="debit"
    )
    assert balance == Decimal("0")


def test_balanced_debit_credit_account_nets_to_zero() -> None:
    balance = compute_account_balance(
        total_debit=Decimal("500"), total_credit=Decimal("500"), normal_side="credit"
    )
    assert balance == Decimal("0")
