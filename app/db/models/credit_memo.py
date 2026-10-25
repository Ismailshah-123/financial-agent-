"""
app.db.models.credit_memo
============================
`ARCreditMemo` (+ `ARCreditMemoLine`) and `APCreditMemo` (+
`APCreditMemoLine`) — credit notes on each side of the ledger. Both
share the exact same lifecycle (`CreditMemoStatus`: draft -> posted ->
applied against an invoice, or void) and structure; they're kept as two
distinct tables rather than one polymorphic table because which party
they're issued to/by (customer vs. vendor) and which invoice type they
apply against (`ARInvoice` vs. `Invoice`) genuinely differ — a shared
table would need nullable FKs to both `customers` and `vendors` plus a
discriminator column, which is more complexity than two small parallel
tables.

WHAT EACH ONE MEANS
----------------------
- `ARCreditMemo`: WE issue this TO a customer — reduces what they owe
  us. Common causes: returned goods, a billing error, a goodwill
  discount. SAP B1 calls this "A/R Credit Memo" (Service Layer resource
  `CreditNotes`, DI API object `oCreditNotes`).
- `APCreditMemo`: a VENDOR issues this TO us — reduces what we owe
  them. Common causes: we returned goods to them, or they overbilled
  us. SAP B1 calls this "A/P Credit Memo" (Service Layer resource
  `PurchaseCreditNotes`, DI API object `oPurchaseCreditNotes`).

See `app.core.sap_reference` for the full object-type mapping table.

`related_invoice_id` is nullable on both — a credit memo can be issued
standalone (not tied to a specific original invoice), though in
practice most are. When present, `PostingService` (extended in the next
phase alongside the AR services) will apply the credit against that
invoice's outstanding balance rather than leaving it as a floating
credit.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Currency
from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import CreditMemoStatus


class ARCreditMemo(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, AuditMixin):
    __tablename__ = "ar_credit_memos"

    credit_memo_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False, index=True
    )
    related_ar_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ar_invoices.id"), nullable=True, index=True
    )

    status: Mapped[CreditMemoStatus] = mapped_column(
        String(16), nullable=False, default=CreditMemoStatus.DRAFT.value
    )
    currency: Mapped[Currency] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    memo_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(
        String(255), nullable=True, doc="e.g. 'return', 'pricing_error', 'goodwill'."
    )

    sap_doc_entry: Mapped[int | None] = mapped_column(nullable=True)

    customer: Mapped["Customer"] = relationship()  # noqa: F821
    related_ar_invoice: Mapped["ARInvoice | None"] = relationship()  # noqa: F821
    lines: Mapped[list["ARCreditMemoLine"]] = relationship(
        back_populates="credit_memo", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ARCreditMemo id={self.id} number={self.credit_memo_number!r} status={self.status}>"


class ARCreditMemoLine(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "ar_credit_memo_lines"

    ar_credit_memo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ar_credit_memos.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    credit_memo: Mapped["ARCreditMemo"] = relationship(back_populates="lines")


class APCreditMemo(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, AuditMixin):
    __tablename__ = "ap_credit_memos"

    credit_memo_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False, index=True
    )
    related_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True, index=True
    )

    status: Mapped[CreditMemoStatus] = mapped_column(
        String(16), nullable=False, default=CreditMemoStatus.DRAFT.value
    )
    currency: Mapped[Currency] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    memo_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    sap_doc_entry: Mapped[int | None] = mapped_column(nullable=True)

    vendor: Mapped["Vendor"] = relationship()  # noqa: F821
    related_invoice: Mapped["Invoice | None"] = relationship()  # noqa: F821
    lines: Mapped[list["APCreditMemoLine"]] = relationship(
        back_populates="credit_memo", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<APCreditMemo id={self.id} number={self.credit_memo_number!r} status={self.status}>"


class APCreditMemoLine(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "ap_credit_memo_lines"

    ap_credit_memo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ap_credit_memos.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    credit_memo: Mapped["APCreditMemo"] = relationship(back_populates="lines")
