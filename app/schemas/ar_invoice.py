"""
app.schemas.ar_invoice
=========================
Request/response shapes for AR Invoices — the mirror of
`app.schemas.invoice`. `amount_paid` and `amount_credited` are never
client-settable on create; they move only through
`IncomingPaymentService` and `CreditMemoService` respectively (see
`ARInvoiceService.apply_balance_change`), and are exposed read-only here
so a client can see the current balance breakdown.

`tax_code` is optional, same pattern as `app.schemas.invoice.InvoiceCreate`:
when supplied, `ARInvoiceService.ingest_invoice` computes
`tax_amount`/`total_amount` server-side via `TaxCalculationService`
using the invoice's own `invoice_date`, overriding the client-supplied
flat values.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field, model_validator

from app.core.constants import Currency
from app.db.models.enums import ARInvoiceStatus
from app.schemas.common import APIModel


class ARInvoiceLineCreate(APIModel):
    line_number: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)


class ARInvoiceLineRead(APIModel):
    id: uuid.UUID
    line_number: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class ARInvoiceCreate(APIModel):
    invoice_number: str = Field(min_length=1, max_length=64)
    customer_id: uuid.UUID
    currency: Currency
    subtotal: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(
        default=Decimal("0"), ge=0, description="Ignored and recomputed if tax_code is also supplied."
    )
    total_amount: Decimal = Field(
        gt=0, description="Ignored and recomputed if tax_code is also supplied."
    )
    tax_code: str | None = Field(
        default=None,
        max_length=64,
        description="If supplied, tax_amount/total_amount are computed "
        "server-side via TaxCalculationService instead of trusting the "
        "values above.",
    )
    invoice_date: date
    due_date: date
    lines: list[ARInvoiceLineCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def _due_date_not_before_invoice_date(self) -> "ARInvoiceCreate":
        if self.due_date < self.invoice_date:
            raise ValueError("due_date cannot be before invoice_date.")
        return self


class ARInvoiceRead(APIModel):
    id: uuid.UUID
    invoice_number: str
    customer_id: uuid.UUID
    status: ARInvoiceStatus
    currency: Currency
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    amount_paid: Decimal
    amount_credited: Decimal
    invoice_date: date
    due_date: date
    lines: list[ARInvoiceLineRead]
