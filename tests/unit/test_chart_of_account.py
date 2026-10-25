"""
Unit tests for app.db.models.chart_of_account.ChartOfAccount.normal_side
— pure property logic, no DB needed. Particular focus on the contra-
account flip, since that's the easiest thing to get backwards in a
hand-authored chart of accounts.
"""

from __future__ import annotations

from app.db.models.chart_of_account import ChartOfAccount
from app.db.models.enums import AccountType


def _account(account_type: AccountType, is_contra: bool = False) -> ChartOfAccount:
    account = ChartOfAccount(
        account_code="TEST-1",
        account_name="Test Account",
        account_type=account_type.value,
        is_contra=is_contra,
    )
    return account


def test_asset_is_debit_normal() -> None:
    assert _account(AccountType.ASSET).normal_side == "debit"


def test_expense_is_debit_normal() -> None:
    assert _account(AccountType.EXPENSE).normal_side == "debit"


def test_liability_is_credit_normal() -> None:
    assert _account(AccountType.LIABILITY).normal_side == "credit"


def test_equity_is_credit_normal() -> None:
    assert _account(AccountType.EQUITY).normal_side == "credit"


def test_revenue_is_credit_normal() -> None:
    assert _account(AccountType.REVENUE).normal_side == "credit"


def test_contra_expense_flips_to_credit_normal() -> None:
    """Purchase Returns: an EXPENSE account that's contra — it reduces
    net expense, so its normal balance is credit, not debit."""
    assert _account(AccountType.EXPENSE, is_contra=True).normal_side == "credit"


def test_contra_asset_flips_to_credit_normal() -> None:
    """e.g. Accumulated Depreciation — a contra-asset."""
    assert _account(AccountType.ASSET, is_contra=True).normal_side == "credit"


def test_contra_liability_flips_to_debit_normal() -> None:
    assert _account(AccountType.LIABILITY, is_contra=True).normal_side == "debit"


def test_contra_revenue_flips_to_debit_normal() -> None:
    """e.g. Sales Returns and Allowances — a contra-revenue account."""
    assert _account(AccountType.REVENUE, is_contra=True).normal_side == "debit"
