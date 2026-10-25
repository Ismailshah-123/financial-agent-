"""
app.db.models.vendor
=====================
The `Vendor` (supplier) master record. Every Accounts Payable document
(Purchase Order, Goods Receipt, Invoice, Payment) references a Vendor.

FIELDS OF NOTE
--------------
- `sap_business_partner_code`: nullable now, populated once the SAP
  Business One integration (Phase 2) syncs Business Partners. Kept on
  this model from day one rather than bolted on later, since retrofitting
  an external-id column onto a table with production data is exactly
  the kind of migration pain this schema is designed to avoid.
- `risk_rating`: 0-100, maintained by the Fraud Detection agent (Phase 2)
  and by manual compliance review. Nullable until that agent exists;
  `AccountsPayableAgent` reads it (when present) as one signal feeding
  a decision's risk_level.
- `approval_limit`: the maximum invoice amount this vendor's invoices can
  be auto-matched for without escalating risk_level — a per-vendor policy
  knob, distinct from a *user's* approval limit (which lives on the user/
  role model, added when auth's user table is built).
- Soft-deleted, never hard-deleted (`SoftDeleteMixin`): financial audit
  trails must be able to resolve a vendor referenced by a five-year-old
  invoice even if that vendor relationship has since ended.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Currency
from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import FilerStatus, VendorStatus


class Vendor(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, AuditMixin):
    __tablename__ = "vendors"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address_line: Mapped[str | None] = mapped_column(String(500), nullable=True)

    bank_account_iban: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bank_account_swift: Mapped[str | None] = mapped_column(String(32), nullable=True)

    default_currency: Mapped[Currency] = mapped_column(
        String(3), nullable=False, default=Currency.USD.value
    )
    payment_terms_days: Mapped[int] = mapped_column(nullable=False, default=30)
    approval_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
        doc="Max invoice amount auto-matchable without escalated risk. "
        "NULL means no vendor-specific override; the role/user limit governs.",
    )

    status: Mapped[VendorStatus] = mapped_column(
        String(32), nullable=False, default=VendorStatus.PENDING_REVIEW.value
    )
    risk_rating: Mapped[int | None] = mapped_column(
        nullable=True, doc="0-100, maintained by the Fraud Detection agent."
    )
    is_1099_vendor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    sap_business_partner_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    filer_status: Mapped[FilerStatus | None] = mapped_column(
        String(16),
        nullable=True,
        doc="Active-taxpayer-list status for withholding tax rate selection "
        "(see app.db.models.enums.FilerStatus). NULL means unknown — "
        "PaymentService treats unknown as non-filer, the more conservative "
        "assumption, not the lower filer rate.",
    )

    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(  # noqa: F821
        back_populates="vendor"
    )
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="vendor")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover — debugging aid only
        return f"<Vendor id={self.id} name={self.name!r} status={self.status}>"
