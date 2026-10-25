"""
app.db.models.customer
========================
The `Customer` master record — the Accounts Receivable mirror of
`Vendor`. Every AR document (`ARInvoice`, `ARCreditMemo`) references a
Customer.

WHY CUSTOMER AND VENDOR ARE SEPARATE TABLES, NOT A UNIFIED
BUSINESS PARTNER TABLE
-----------------------------------------------------------------------
SAP Business One itself models both as one `OCRD` (Business Partners)
table distinguished by `CardType` ('C' customer / 'S' vendor / 'L'
lead). This platform deliberately does NOT mirror that here — two
separate tables (`vendors`, `customers`) with independent status
vocab, independent limits (`Vendor.approval_limit` vs
`Customer.credit_limit`, which mean opposite things — how much we can
owe them vs. how much they can owe us), and independent risk scoring.

This is a considered tradeoff, not an oversight:
    - Most of this platform's query patterns are AP-only or AR-only
      (an AP invoice never needs to join against customers), so
      separate tables keep those queries simpler and their indexes
      smaller.
    - A single party is occasionally both a customer AND a vendor to
      the same company (e.g. a supplier who also buys your product) —
      a unified BP table would need a `CardType` (or a set of role
      flags) to distinguish which relationship a given document is
      using anyway, so the unification doesn't actually remove a field,
      it just moves it.
    - The SAP Business One Service Layer sync (Phase 2) can still map
      cleanly either way: `Vendor.sap_business_partner_code` and
      `Customer.sap_business_partner_code` both point at the same
      `OCRD.CardCode` namespace in SAP, just filtered by `CardType` on
      the SAP side during sync. See `app.core.sap_reference` for the
      object-type mapping this relies on.

If a future requirement genuinely needs one party tracked as both
customer and vendor with shared identity (not just shared tax id), that
argues for a real `BusinessPartner` parent table with `Vendor`/
`Customer` as role-specific extensions — worth revisiting then, not
speculatively built now.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Currency
from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import CustomerStatus


class Customer(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, AuditMixin):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address_line: Mapped[str | None] = mapped_column(String(500), nullable=True)

    default_currency: Mapped[Currency] = mapped_column(
        String(3), nullable=False, default=Currency.USD.value
    )
    payment_terms_days: Mapped[int] = mapped_column(
        nullable=False, default=30, doc="Terms we extend to this customer (Net 30, etc.)."
    )
    credit_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
        doc="Max outstanding AR balance permitted for this customer. NULL "
        "means no limit configured — treated as unlimited, not zero, by "
        "any future credit-hold logic that reads this field.",
    )

    status: Mapped[CustomerStatus] = mapped_column(
        String(32), nullable=False, default=CustomerStatus.PENDING_REVIEW.value
    )
    risk_rating: Mapped[int | None] = mapped_column(
        nullable=True, doc="0-100, maintained by the Fraud Detection agent (Phase 2)."
    )

    sap_business_partner_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )

    invoices: Mapped[list["ARInvoice"]] = relationship(back_populates="customer")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Customer id={self.id} name={self.name!r} status={self.status}>"
