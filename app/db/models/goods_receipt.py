"""
app.db.models.goods_receipt
=============================
`GoodsReceipt` (GRPO — Goods Receipt PO) + `GoodsReceiptLine`: records
that goods/services against a Purchase Order line were actually
received. This is the third leg of the 3-way match — without a posted
goods receipt, the Accounts Payable agent can only perform a 2-way match
(PO <-> Invoice) and must record `MatchType.TWO_WAY`, which carries a
higher risk classification than `THREE_WAY` (see the AP agent's matching
logic, added next).

`GoodsReceiptLine.purchase_order_line_id` links back to the specific PO
line it fulfills (not just the parent PO) so partial receipts against a
multi-line PO are matched at the correct granularity.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, AuditMixin
from app.db.models.enums import GoodsReceiptStatus
from sqlalchemy import String


class GoodsReceipt(Base, UUIDPrimaryKeyMixin, TimestampMixin, AuditMixin):
    __tablename__ = "goods_receipts"

    grpo_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    status: Mapped[GoodsReceiptStatus] = mapped_column(
        String(32), nullable=False, default=GoodsReceiptStatus.DRAFT.value
    )
    received_date: Mapped[date] = mapped_column(Date, nullable=False)

    sap_doc_entry: Mapped[int | None] = mapped_column(nullable=True)

    lines: Mapped[list["GoodsReceiptLine"]] = relationship(
        back_populates="goods_receipt", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GoodsReceipt id={self.id} grpo_number={self.grpo_number!r}>"


class GoodsReceiptLine(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "goods_receipt_lines"

    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goods_receipts.id"), nullable=False, index=True
    )
    purchase_order_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_order_lines.id"), nullable=False, index=True
    )
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)

    goods_receipt: Mapped["GoodsReceipt"] = relationship(back_populates="lines")
    purchase_order_line: Mapped["PurchaseOrderLine"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GoodsReceiptLine grpo={self.goods_receipt_id} po_line={self.purchase_order_line_id}>"
