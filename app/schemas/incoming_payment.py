"""
app.schemas.incoming_payment
===============================
Request/response shapes for Incoming Payments — the AR mirror of
`app.schemas.payment`. Unlike `PaymentCreate` (AP side, where amount is
always the full invoice total, taken server-side), `IncomingPaymentCreate`
DOES accept a client-specified `amount`, because AR payments are
routinely partial — a customer paying half an invoice now and the rest
later is normal, not an edge case. `IncomingPaymentService` validates
that amount doesn't exceed what's still outstanding.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field

from app.core.constants import Currency
from app.db.models.enums import PaymentStatus
from app.schemas.common import APIModel


class IncomingPaymentCreate(APIModel):
    ar_invoice_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    payment_method: str = Field(min_length=1, max_length=32)
    received_date: date
    bank_reference: str | None = Field(default=None, max_length=128)


class IncomingPaymentRead(APIModel):
    id: uuid.UUID
    payment_number: str
    customer_id: uuid.UUID
    ar_invoice_id: uuid.UUID
    status: PaymentStatus
    amount: Decimal
    currency: Currency
    payment_method: str
    received_date: date
    bank_reference: str | None
