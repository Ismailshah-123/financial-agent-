"""
app.schemas.payment
=====================
Request/response shapes for Outgoing Payments.

There is no `PaymentUpdate` schema: once a payment exists it only moves
forward through `PaymentStatus` via dedicated action endpoints
(`approve`, `execute`, `cancel` — added with `app.api.v1.payments` in
the API phase), never via a generic field-level PATCH. A payment is the
platform's highest-consequence object; allowing arbitrary field edits on
it (e.g. silently changing `amount` after approval) is exactly the kind
of gap that turns into fraud. `PaymentCreate` only captures scheduling
intent — the amount is always taken from the source invoice server-side,
never typed in independently by the caller.

`withholding_tax_code` is optional: when supplied, `PaymentService`
computes the withheld amount via `TaxCalculationService` and stores the
NET transfer amount on `amount`; `amount` still means "invoice total"
when withholding isn't used. See `PaymentService.schedule_payment`'s
docstring.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field

from app.core.constants import Currency
from app.db.models.enums import PaymentStatus
from app.schemas.common import APIModel


class PaymentCreate(APIModel):
    invoice_id: uuid.UUID
    payment_method: str = Field(min_length=1, max_length=32)
    scheduled_date: date
    withholding_tax_code: str | None = Field(
        default=None,
        description="Optional TaxCode.code for Section-153-style withholding. "
        "When set, the actual transfer (amount) is net of the withheld "
        "portion — see PaymentService.schedule_payment.",
    )


class PaymentRead(APIModel):
    id: uuid.UUID
    payment_number: str
    vendor_id: uuid.UUID
    invoice_id: uuid.UUID
    status: PaymentStatus
    amount: Decimal
    currency: Currency
    payment_method: str
    scheduled_date: date
    executed_date: date | None
    bank_reference: str | None
    failure_reason: str | None
    withholding_tax_code: str | None
    withholding_tax_amount: Decimal
