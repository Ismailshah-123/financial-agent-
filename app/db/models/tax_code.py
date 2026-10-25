"""
app.db.models.tax_code
=========================
`TaxCode`: configurable tax reference data — sales tax rates,
withholding tax rates, whatever a deployment's jurisdiction requires.
Deliberately a database table, not a hardcoded constant like
`app.services.posting_service.DefaultAccounts`, because tax rates are
NOT stable the way chart-of-accounts codes are: Pakistan's federal
budget (typically announced each June) can change GST and withholding
rates, withholding rates additionally vary by filer/non-filer status
and transaction type under Section 153 of the Income Tax Ordinance
2001, and any deployment outside Pakistan needs entirely different
codes. Hardcoding any of this would be wrong within a year, possibly
within a budget cycle — see `app.services.tax_service` for the
calculation logic and its own verification warnings.

EFFECTIVE-DATED RATES
-------------------------
`effective_from` / `effective_to` let more than one row share the same
logical `code` over time (e.g. a rate change mid-year) — an invoice
dated in a prior period must use the rate that was actually in effect
then, not today's rate. `TaxCalculationService` resolves this by
querying for the row whose effective range covers the invoice's date,
never just "the current row."

*** RATES SEEDED BY `alembic/versions/0005_tax_codes.py` ARE A STARTING
POINT, NOT VERIFIED-CURRENT VALUES. Pakistan's standard federal Sales
Tax rate (18%) has been stable for a long period, but withholding tax
rates under Section 153 vary by filer status and category and change
more frequently. Confirm every seeded rate against current FBR
notifications before relying on this for real tax filings. ***
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import TaxType


class TaxCode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tax_codes"

    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tax_type: Mapped[TaxType] = mapped_column(String(20), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(
        String(32), nullable=False, doc="e.g. 'PK-FEDERAL', 'PK-SINDH', 'PK-PUNJAB'."
    )
    rate_percent: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), nullable=False, doc="e.g. 18.000 for 18%. Applied as subtotal * rate/100."
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(
        Date, nullable=True, doc="NULL means currently open-ended / still in effect."
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="e.g. filer/non-filer condition, category applicability — free text since "
        "these conditions vary too much to model as structured columns yet.",
    )

    def covers(self, as_of: date) -> bool:
        """Whether this rate row was in effect on a given date — what
        TaxCalculationService uses to pick the right historical rate."""
        if as_of < self.effective_from:
            return False
        if self.effective_to is not None and as_of > self.effective_to:
            return False
        return True

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TaxCode code={self.code!r} rate={self.rate_percent}% type={self.tax_type}>"
