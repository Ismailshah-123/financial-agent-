"""
app.schemas.budget
======================
Request/response shapes for `app.api.v1.budgets`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from app.core.constants import Currency
from app.schemas.common import APIModel


class BudgetCreate(APIModel):
    name: str
    account_code: str
    period_start: date
    period_end: date
    budgeted_amount: Decimal
    currency: Currency
    notes: str | None = None


class BudgetRead(APIModel):
    id: uuid.UUID
    name: str
    account_code: str
    period_start: date
    period_end: date
    budgeted_amount: Decimal
    currency: str
    notes: str | None
    created_at: datetime
