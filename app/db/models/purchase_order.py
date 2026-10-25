"""
app.db.models.purchase_order
=============================
`PurchaseOrder` + `PurchaseOrderLine`: the "PO" side of the 3-way match
(Purchase Order <-> Goods Receipt <-> Invoice) that the Accounts Payable
agent performs before recommending payment.

A PO is line-item based (`PurchaseOrderLine`) rather than a single total,
because matching happens at the line level in real AP workflows — an
invoice can partially match a PO (some lines fully received and
invoiced, others still open), and the agent's decision needs to reason
about which specific lines matched and which didn't (see
`SupportingEvidence` in app.agents.schemas).

`po_number` is unique and human-readable (not just the UUID `id`) because
it's what appears on vendor-facing documents and, eventually, what SAP
Business One's DI API expects to reconcile against.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Currency
from app.db.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import PurchaseOrderStatus


class PurchaseOrder(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, AuditMixin):
    __tablename__ = "purchase_orders"

    po_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False, index=True
    )

    status: Mapped[PurchaseOrderStatus] = mapped_column(
        String(32), nullable=False, default=PurchaseOrderStatus.DRAFT.value
    )
    currency: Mapped[Currency] = mapped_column(String(3), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    sap_doc_entry: Mapped[int | None] = mapped_column(
        nullable=True, doc="SAP Business One DocEntry once synced (Phase 2)."
    )

    vendor: Mapped["Vendor"] = relationship(back_populates="purchase_orders")  # noqa: F821
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan", order_by="PurchaseOrderLine.line_number"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PurchaseOrder id={self.id} po_number={self.po_number!r} status={self.status}>"


class PurchaseOrderLine(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        UniqueConstraint("purchase_order_id", "line_number", name="uq_po_line_number"),
    )

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    item_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity_ordered: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PurchaseOrderLine po={self.purchase_order_id} line={self.line_number}>"
