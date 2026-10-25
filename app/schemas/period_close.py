"""
app.schemas.period_close
===========================
Request/response shapes for `app.api.v1.period_close`. Unlike
`app.schemas.financial_report` (read-only, computed on demand),
`PeriodClose` is a real persisted row — `PeriodCloseRead` mirrors the
model field-for-field, same `from_attributes=True` pattern.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from app.schemas.common import APIModel


class ClosePeriodRequest(APIModel):
    start_date: date
    end_date: date


class ReopenPeriodRequest(APIModel):
    reason: str


class PeriodCloseRead(APIModel):
    id: uuid.UUID
    start_date: date
    end_date: date
    closing_journal_entry_id: uuid.UUID
    total_revenue: Decimal
    total_expense: Decimal
    net_income: Decimal
    is_reopened: bool
    reopened_at: datetime | None
    reopen_reason: str | None
    reopening_journal_entry_id: uuid.UUID | None
    created_at: datetime
