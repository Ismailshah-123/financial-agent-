"""
app.schemas.credit_memo
==========================
Request/response shapes for both `ARCreditMemo` and `APCreditMemo` — see
`app.db.models.credit_memo` for why they're modeled as parallel but
separate resources rather than one polymorphic one.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field

from app.core.constants import Currency
from app.db.models.enums import CreditMemoStatus
from app.schemas.common import APIModel


class CreditMemoLineCreate(APIModel):
    line_number: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)


class CreditMemoLineRead(APIModel):
    id: uuid.UUID
    line_number: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class ARCreditMemoCreate(APIModel):
    credit_memo_number: str = Field(min_length=1, max_length=64)
    customer_id: uuid.UUID
    related_ar_invoice_id: uuid.UUID | None = None
    currency: Currency
    subtotal: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)
    total_amount: Decimal = Field(gt=0)
    memo_date: date
    reason: str | None = Field(default=None, max_length=255)
    lines: list[CreditMemoLineCreate] = Field(min_length=1)


class ARCreditMemoRead(APIModel):
    id: uuid.UUID
    credit_memo_number: str
    customer_id: uuid.UUID
    related_ar_invoice_id: uuid.UUID | None
    status: CreditMemoStatus
    currency: Currency
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    memo_date: date
    reason: str | None
    lines: list[CreditMemoLineRead]


class APCreditMemoCreate(APIModel):
    credit_memo_number: str = Field(min_length=1, max_length=64)
    vendor_id: uuid.UUID
    related_invoice_id: uuid.UUID | None = None
    currency: Currency
    subtotal: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)
    total_amount: Decimal = Field(gt=0)
    memo_date: date
    reason: str | None = Field(default=None, max_length=255)
    lines: list[CreditMemoLineCreate] = Field(min_length=1)


class APCreditMemoRead(APIModel):
    id: uuid.UUID
    credit_memo_number: str
    vendor_id: uuid.UUID
    related_invoice_id: uuid.UUID | None
    status: CreditMemoStatus
    currency: Currency
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    memo_date: date
    reason: str | None
    lines: list[CreditMemoLineRead]
