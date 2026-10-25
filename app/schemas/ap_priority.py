"""
app.schemas.ap_priority
===========================
Response shapes for `app.api.v1.ap_priority`, wrapping the plain
dataclasses in `app.services.ap_priority_calculations` the same way
`app.schemas.aging` wraps `aging_calculations` — see that module's own
docstring for why `model_validate(..., from_attributes=True)` works
directly against a dataclass instance here, no dict conversion needed.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field

from app.schemas.common import APIModel
from app.services.ap_priority_calculations import DueBucket, PaymentPriorityStatus, PriorityTier


class PaymentObligationRead(APIModel):
    invoice_id: uuid.UUID
    invoice_number: str
    vendor_id: uuid.UUID
    vendor_name: str
    amount: Decimal
    currency: str
    due_date: date
    as_of: date
    days_until_due: int
    due_bucket: DueBucket
    status: PaymentPriorityStatus
    priority_score: int | None
    priority: PriorityTier | None
    reason: str
    scheduled_date: date | None
    executed_date: date | None


class VendorCurrencyExposureRead(APIModel):
    currency: str
    total_exposure: Decimal
    open_invoice_count: int
    overdue_amount: Decimal
    overdue_invoice_count: int
    blocked_count: int
    payment_failed_count: int
    awaiting_approval_count: int
    highest_priority: PriorityTier


class APPriorityCurrencySummaryRead(APIModel):
    currency: str
    total_payable: Decimal
    open_obligation_count: int
    overdue_amount: Decimal
    overdue_count: int
    by_status_count: dict[str, int]
    by_status_amount: dict[str, Decimal]
    executed_last_30_days_amount: Decimal
    executed_last_30_days_count: int


class VendorExposureRead(APIModel):
    vendor_id: uuid.UUID
    vendor_name: str
    currency: str | None
    total_exposure: Decimal | None
    open_invoice_count: int
    overdue_amount: Decimal | None
    overdue_invoice_count: int
    blocked_count: int
    payment_failed_count: int
    awaiting_approval_count: int
    highest_priority: PriorityTier
    currency_balances: list[VendorCurrencyExposureRead] = Field(default_factory=list)


class APPrioritySummaryRead(APIModel):
    as_of: date
    currency: str | None = None
    total_payable: Decimal | None
    open_obligation_count: int
    overdue_amount: Decimal | None
    overdue_count: int
    by_status_count: dict[str, int] = Field(
        description="Open (non-executed) obligation count per PaymentPriorityStatus value."
    )
    by_status_amount: dict[str, Decimal] = Field(
        description="Amount by status when one currency is in scope; use currency_balances for mixed currencies."
    )
    executed_last_30_days_amount: Decimal | None
    executed_last_30_days_count: int
    currency_balances: list[APPriorityCurrencySummaryRead] = Field(default_factory=list)
