"""
app.schemas.invoice
=====================
Request/response shapes for AP Invoices.

`InvoiceCreate` models the two real ingestion paths: manual entry (a
clerk types in the fields) and OCR ingestion (`source_document_id` is
set, `ocr_extracted_data` carries the raw extraction, and lines may
arrive pre-populated from the OCR pipeline). Both paths converge on the
same shape so `InvoiceIngestionService` (next phase) doesn't need two
separate code paths downstream of validation.

`tax_code` is optional. When supplied, `InvoiceService.ingest_invoice`
computes `tax_amount` (and therefore `total_amount`) server-side via
`TaxCalculationService` using the invoice's own `invoice_date` for
effective-rate resolution — the client-supplied `tax_amount`/
`total_amount` are IGNORED and overridden in that case, since letting a
client assert both a tax code and a contradicting flat amount would
create two sources of truth. Omit `tax_code` to keep the original
behavior: a flat, client-supplied `tax_amount`.

`match_type`, `match_confidence`, `matched_at`, and `status` are never
client-settable — they are exclusively written by
`AccountsPayableAgent` / the matching service, which is the whole point
of having an agent reason about them rather than trusting client input
for something that gates payment.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field, model_validator

from app.core.constants import Currency
from app.db.models.enums import InvoiceStatus, MatchType
from app.schemas.common import APIModel


class InvoiceLineCreate(APIModel):
    line_number: int = Field(ge=1)
    purchase_order_line_id: uuid.UUID | None = None
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)


class InvoiceLineRead(APIModel):
    id: uuid.UUID
    line_number: int
    purchase_order_line_id: uuid.UUID | None
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class InvoiceCreate(APIModel):
    invoice_number: str = Field(min_length=1, max_length=64)
    vendor_id: uuid.UUID
    purchase_order_id: uuid.UUID | None = None
    currency: Currency
    subtotal: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Ignored and recomputed if tax_code is also supplied.",
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
    source_document_id: str | None = Field(default=None, max_length=128)
    lines: list[InvoiceLineCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def _due_date_not_before_invoice_date(self) -> "InvoiceCreate":
        if self.due_date < self.invoice_date:
            raise ValueError("due_date cannot be before invoice_date.")
        return self


class InvoiceRead(APIModel):
    id: uuid.UUID
    invoice_number: str
    vendor_id: uuid.UUID
    purchase_order_id: uuid.UUID | None
    status: InvoiceStatus
    currency: Currency
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    invoice_date: date
    due_date: date
    match_type: MatchType | None
    match_confidence: Decimal | None
    matched_at: date | None
    lines: list[InvoiceLineRead]
