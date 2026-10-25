"""
app.schemas.fbr_remittance
==============================
Request/response shapes for `app.api.v1.fbr_remittances`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from app.core.constants import Currency
from app.schemas.common import APIModel


class FBRRemittanceCreate(APIModel):
    period_start: date
    period_end: date
    amount_remitted: Decimal
    currency: Currency
    remitted_date: date
    fbr_reference: str
    notes: str | None = None


class FBRRemittanceRead(APIModel):
    id: uuid.UUID
    period_start: date
    period_end: date
    amount_remitted: Decimal
    currency: str
    remitted_date: date
    fbr_reference: str
    notes: str | None
    created_at: datetime
