"""
app.db.models.ar_invoice
==========================
`ARInvoice` + `ARInvoiceLine`: an invoice issued TO a customer (revenue
recognized, receivable created) — the mirror image of `Invoice`
(app.db.models.invoice), which is a vendor invoice received FROM a
supplier (expense recognized, payable created). SAP B1 calls this
document type "A/R Invoice" (Service Layer resource `Invoices`, DI API
object `oInvoices`) — see `app.core.sap_reference` for the object-type
mapping.

`amount_paid` and `amount_credited` are tracked as separate running
totals — `amount_paid` moves only via `IncomingPaymentService` (real
cash received), `amount_credited` moves only via `CreditMemoService`
(credit memo application). Keeping them separate (rather than one
combined column) is what lets AR reporting later answer "how much of
this invoice was actually collected in cash" vs. "how much was written
off/credited" as two different questions — conflating them was a
documented limitation in an earlier phase; the schema now keeps them
apart from the start.

There is deliberately no `sales_order_id` — a `SalesOrder` model doesn't
exist yet (AR's mirror of `PurchaseOrder`). An AR invoice can exist
without one (many businesses invoice directly, without a formal SO
step), same as how `Invoice.purchase_order_id` is nullable on the AP
side for non-PO invoices.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.constants import Currency
from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import ARInvoiceStatus


class ARInvoice(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, AuditMixin):
    __tablename__ = "ar_invoices"

    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False, index=True
    )

    status: Mapped[ARInvoiceStatus] = mapped_column(
        String(32), nullable=False, default=ARInvoiceStatus.DRAFT.value, index=True
    )
    currency: Mapped[Currency] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, doc="Cash received, via IncomingPaymentService only."
    )
    amount_credited: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, doc="Credit memos applied, via CreditMemoService only."
    )

    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    sap_doc_entry: Mapped[int | None] = mapped_column(nullable=True)

    customer: Mapped["Customer"] = relationship(back_populates="invoices")  # noqa: F821
    lines: Mapped[list["ARInvoiceLine"]] = relationship(
        back_populates="ar_invoice", cascade="all, delete-orphan", order_by="ARInvoiceLine.line_number"
    )

    @property
    def amount_outstanding(self) -> Decimal:
        return self.total_amount - self.amount_paid - self.amount_credited

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ARInvoice id={self.id} invoice_number={self.invoice_number!r} status={self.status}>"


class ARInvoiceLine(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "ar_invoice_lines"

    ar_invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ar_invoices.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    ar_invoice: Mapped["ARInvoice"] = relationship(back_populates="lines")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ARInvoiceLine invoice={self.ar_invoice_id} line={self.line_number}>"
