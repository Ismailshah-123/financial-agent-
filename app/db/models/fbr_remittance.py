"""
app.db.models.fbr_remittance
================================
`FBRRemittance`: one row per payment made TO FBR (Pakistan's Federal
Board of Revenue) for withholding tax collected FROM vendors during a
period. See `alembic/versions/0010_fbr_remittance.py` for why this
table exists — it's the record of the liability
`DefaultAccounts.WITHHOLDING_TAX_PAYABLE` (2100-WHT) tracks actually
being paid off, which nothing before this recorded.

Not a journal entry, not something `PostingService` touches — same
"planning/compliance record, not a ledger posting" pattern as `Budget`.
`app.services.fbr_compliance_service.FBRComplianceService` compares
this against the 2100-WHT liability incurred in the same period; it
never posts anything itself.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import Currency
from app.db.base import AuditMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin


class FBRRemittance(Base, UUIDPrimaryKeyMixin, TimestampMixin, AuditMixin):
    __tablename__ = "fbr_remittances"

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount_remitted: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(String(3), nullable=False)
    remitted_date: Mapped[date] = mapped_column(Date, nullable=False)
    fbr_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<FBRRemittance id={self.id} {self.period_start}..{self.period_end} "
            f"{self.amount_remitted} ref={self.fbr_reference}>"
        )
