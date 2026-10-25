"""
app.schemas.aging
====================
Response shapes for `app.api.v1.aging`. These are thin `APIModel`
wrappers around the plain dataclasses in `app.services.aging_calculations`
(`InvoiceAgingRecord`, `CustomerAgingSummary`, `PortfolioAgingSummary`) —
built with `model_validate(..., from_attributes=True)` the same way
every other `*Read` schema in this codebase wraps an ORM row, except
the source here is a dataclass instead of a SQLAlchemy model.
`AgingBucket` itself is imported from the calculations module rather
than redefined here, so the bucket vocabulary has exactly one
definition across the whole platform (pure logic layer and API layer
included) — see that module's own docstring on why drift like that is
worth actively avoiding.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field

from app.schemas.common import APIModel
from app.services.aging_calculations import AgingBucket, PriorityTier


class InvoiceAgingRead(APIModel):
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


class CustomerCurrencyBalanceRead(APIModel):
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
    priority_reasons: list[str]
    recommended_action: str


class CustomerAgingRead(APIModel):
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
    credit_utilization: Decimal | None = Field(
        default=None,
        description="Null when credit limit is not configured, undefined, or scalar exposure is mixed-currency.",
    )
    priority_score: int = Field(description="0-100, see aging_calculations for the scoring rubric.")
    risk: PriorityTier
    priority: PriorityTier
    priority_reasons: list[str]
    recommended_action: str
    currency_balances: list[CustomerCurrencyBalanceRead] = Field(default_factory=list)


class PortfolioCurrencyBalanceRead(APIModel):
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
    bucket_percentages: dict[str, float] = Field(default_factory=dict)


class PortfolioAgingSummaryRead(APIModel):
    as_of: date
    currency: str | None = None
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
    currency_balances: list[PortfolioCurrencyBalanceRead] = Field(default_factory=list)
    bucket_percentages: dict[str, float] = Field(default_factory=dict)
