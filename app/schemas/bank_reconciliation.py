"""
app.schemas.bank_reconciliation
===================================
Request/response shapes for `app.api.v1.bank_reconciliation`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from app.core.constants import Currency
from app.schemas.common import APIModel


class StatementLineCreate(APIModel):
    transaction_date: date
    description: str
    amount: Decimal
    currency: Currency
    bank_reference: str | None = None


class IngestStatementLinesRequest(APIModel):
    statement_label: str
    lines: list[StatementLineCreate]


class BankStatementLineRead(APIModel):
    id: uuid.UUID
    statement_label: str
    transaction_date: date
    description: str
    amount: Decimal
    currency: str
    bank_reference: str | None
    is_matched: bool
    matched_payment_type: str | None
    matched_payment_id: uuid.UUID | None
    matched_at: datetime | None


class ConfirmMatchRequest(APIModel):
    payment_type: str
    payment_id: uuid.UUID
