"""
app.schemas.customer
======================
Request/response shapes for Customers — the AR mirror of
`app.schemas.vendor`. Same pattern: `status` and `risk_rating` are
system-controlled, never client-settable on create/update.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import EmailStr, Field

from app.core.constants import Currency
from app.db.models.enums import CustomerStatus
from app.schemas.common import APIModel


class CustomerBase(APIModel):
    name: str = Field(min_length=1, max_length=255)
    tax_id: str | None = Field(default=None, max_length=64)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=64)
    address_line: str | None = Field(default=None, max_length=500)
    default_currency: Currency = Currency.USD
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    credit_limit: Decimal | None = Field(default=None, ge=0)


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    tax_id: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address_line: str | None = None
    default_currency: Currency | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    credit_limit: Decimal | None = Field(default=None, ge=0)


class CustomerRead(CustomerBase):
    id: uuid.UUID
    status: CustomerStatus
    risk_rating: int | None
    sap_business_partner_code: str | None
