"""
app.schemas.tax_code
=======================
Request/response shapes for Tax Codes. `TaxCodeCreate` is deliberately
open to any `jurisdiction`/`tax_type` — this platform isn't
Pakistan-only, the seeded rates just default to FBR-relevant codes
(see `alembic/versions/0005_tax_codes.py`) since PKR is the primary
deployment currency. A finance admin adds/updates codes as rates change
(the reason this is a database table and not a hardcoded constant — see
`app.db.models.tax_code`'s docstring).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field

from app.db.models.enums import TaxType
from app.schemas.common import APIModel


class TaxCodeCreate(APIModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    tax_type: TaxType
    jurisdiction: str = Field(min_length=1, max_length=32)
    rate_percent: Decimal = Field(ge=0, le=100)
    effective_from: date
    effective_to: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class TaxCodeRead(APIModel):
    id: uuid.UUID
    code: str
    name: str
    tax_type: TaxType
    jurisdiction: str
    rate_percent: Decimal
    effective_from: date
    effective_to: date | None
    is_active: bool
    notes: str | None


class TaxCalculationRequest(APIModel):
    tax_code: str
    base_amount: Decimal = Field(gt=0)
    as_of: date
    calculation_type: TaxType


class TaxCalculationResultRead(APIModel):
    tax_code: str
    tax_type: TaxType
    rate_percent: Decimal
    base_amount: Decimal
    tax_amount: Decimal
