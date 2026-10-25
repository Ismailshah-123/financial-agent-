"""
app.schemas.financial_report
===============================
Response shapes for the financial reporting endpoints
(`app.api.v1.reports`). These mirror the dataclasses in
`app.services.financial_reporting_service` field-for-field — built via
`APIModel.model_validate(report)` (Pydantic's `from_attributes=True`
works directly against plain dataclasses, no manual conversion needed).
There are no request/Create schemas here: every report is read-only,
computed on demand from posted journal entries, never stored. Each report
names the single `currency` it was produced in (see the CURRENCY POLICY in
the reporting service); amounts in different currencies are never combined.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import Field

from app.db.models.enums import AccountType
from app.schemas.common import APIModel


class AccountBalanceRead(APIModel):
    account_code: str
    account_name: str
    account_type: AccountType
    total_debit: Decimal
    total_credit: Decimal
    balance: Decimal


class TrialBalanceRead(APIModel):
    as_of: date
    lines: list[AccountBalanceRead]
    total_debit: Decimal
    total_credit: Decimal
    is_balanced: bool
    currency: str | None = None
    available_currencies: list[str] = Field(default_factory=list)


class ProfitAndLossRead(APIModel):
    start_date: date
    end_date: date
    revenue_lines: list[AccountBalanceRead]
    expense_lines: list[AccountBalanceRead]
    total_revenue: Decimal
    total_expense: Decimal
    net_income: Decimal
    currency: str | None = None
    available_currencies: list[str] = Field(default_factory=list)


class BalanceSheetRead(APIModel):
    as_of: date
    asset_lines: list[AccountBalanceRead]
    liability_lines: list[AccountBalanceRead]
    equity_lines: list[AccountBalanceRead]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    computed_retained_earnings: Decimal
    is_balanced: bool
    currency: str | None = None
    available_currencies: list[str] = Field(default_factory=list)


class ReportCurrenciesRead(APIModel):
    """Currencies that have at least one posted journal entry. Reports are
    produced one currency at a time; no FX conversion exists."""

    currencies: list[str] = Field(default_factory=list)
