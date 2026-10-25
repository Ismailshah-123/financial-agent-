"""
app.schemas.vendor
===================
Request/response shapes for the Vendor API.

`VendorCreate` intentionally excludes `status` and `risk_rating` — those
are system-controlled (a new vendor always starts `PENDING_REVIEW`, and
`risk_rating` is only ever written by the Fraud Detection agent or a
compliance reviewer, never by whoever is creating the vendor record).
`VendorUpdate` makes every field optional (PATCH semantics) but still
excludes `risk_rating`, which gets its own dedicated endpoint/schema
when the Fraud Detection agent is built, so a routine "update the
vendor's phone number" call can never accidentally overwrite a risk
score.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import EmailStr, Field

from app.core.constants import Currency
from app.db.models.enums import FilerStatus, VendorStatus
from app.schemas.common import APIModel


class VendorBase(APIModel):
    name: str = Field(min_length=1, max_length=255)
    tax_id: str | None = Field(default=None, max_length=64)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=64)
    address_line: str | None = Field(default=None, max_length=500)
    bank_account_iban: str | None = Field(default=None, max_length=64)
    bank_account_swift: str | None = Field(default=None, max_length=32)
    default_currency: Currency = Currency.USD
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    approval_limit: Decimal | None = Field(default=None, ge=0)
    is_1099_vendor: bool = False
    filer_status: FilerStatus | None = Field(
        default=None,
        description="Active-taxpayer-list status, drives withholding tax rate "
        "selection. NULL means unknown (treated as non-filer, the more "
        "conservative rate, by PaymentService).",
    )


class VendorCreate(VendorBase):
    pass


class VendorUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    tax_id: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address_line: str | None = None
    bank_account_iban: str | None = None
    bank_account_swift: str | None = None
    default_currency: Currency | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    approval_limit: Decimal | None = Field(default=None, ge=0)
    is_1099_vendor: bool | None = None
    filer_status: FilerStatus | None = None


class VendorRiskAssessmentRequest(APIModel):
    """The dedicated risk_rating endpoint/schema this module's own
    docstring specifies — see above. `new_status` is optional: not
    every risk_rating update warrants a status change (e.g. bumping it
    up after a MEDIUM finding); acting on a CRITICAL finding typically
    means also setting BLOCKED."""

    risk_rating: int = Field(ge=0, le=100)
    new_status: VendorStatus | None = None
    reason: str = Field(min_length=1)


class VendorRead(VendorBase):
    id: uuid.UUID
    status: VendorStatus
    risk_rating: int | None
    sap_business_partner_code: str | None
