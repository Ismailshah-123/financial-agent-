"""
app.db.models.invoice
======================
`Invoice` (an Accounts Payable / vendor invoice) + `InvoiceLine`. This is
the document the Accounts Payable agent's whole workflow revolves around:
ingested (often via OCR from a PDF/image), matched against a Purchase
Order and Goods Receipt, and — once matched and approved — scheduled for
payment.

FIELDS OF NOTE
--------------
- `source_document_id`: pointer to the uploaded file (invoice PDF/image)
  in the document store. The Document AI/OCR pipeline (Phase 2) populates
  `ocr_extracted_data` from that document; this model doesn't duplicate
  document storage, only references it — same pattern as
  `SupportingEvidence` in app.agents.schemas.
- `match_type` / `matched_at` / `match_confidence`: populated by the AP
  agent after `_execute()` runs its matching logic. Kept on the row
  (not just in the agent's `AgentDecision`) so the *current* match state
  is queryable without replaying agent history — the `AgentDecision` in
  the audit trail remains the record of *how* it got there.
- `purchase_order_id` is nullable: not every vendor invoice has a PO
  (e.g. utility bills, subscriptions) — those get `MatchType.MANUAL` and
  a mandatory human review, never an automatic approval path.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Currency
from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import InvoiceStatus, MatchType


class Invoice(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, AuditMixin):
    __tablename__ = "invoices"

    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False, index=True
    )
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=True, index=True
    )

    status: Mapped[InvoiceStatus] = mapped_column(
        String(32), nullable=False, default=InvoiceStatus.RECEIVED.value, index=True
    )
    currency: Mapped[Currency] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    source_document_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, doc="Reference into the document store, not raw content."
    )
    ocr_extracted_data: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, doc="Raw OCR/extraction output for audit/debugging."
    )

    match_type: Mapped[MatchType | None] = mapped_column(String(16), nullable=True)
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    matched_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    sap_doc_entry: Mapped[int | None] = mapped_column(nullable=True)

    vendor: Mapped["Vendor"] = relationship(back_populates="invoices")  # noqa: F821
    purchase_order: Mapped["PurchaseOrder | None"] = relationship()  # noqa: F821
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.line_number"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Invoice id={self.id} invoice_number={self.invoice_number!r} status={self.status}>"


class InvoiceLine(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True
    )
    purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_order_lines.id"), nullable=True
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    invoice: Mapped["Invoice"] = relationship(back_populates="lines")
    purchase_order_line: Mapped["PurchaseOrderLine | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InvoiceLine invoice={self.invoice_id} line={self.line_number}>"
