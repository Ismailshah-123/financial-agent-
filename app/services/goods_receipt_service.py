"""
app.services.goods_receipt_service
=====================================
Use-case layer for Goods Receipts (GRPO). Owns the invariant that a
receipt line can never claim more quantity than is still outstanding on
its Purchase Order line — this is what keeps the 3-way match's "has this
been received" signal trustworthy. Also rolls the parent PO's status
forward (`SENT` -> `PARTIALLY_RECEIVED` -> `FULLY_RECEIVED`) as receipts
post, so the PO's own status is always a correct summary without a
separate reconciliation job.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.core.logging import get_audit_logger, get_logger
from app.db.models.enums import GoodsReceiptStatus, PurchaseOrderStatus
from app.db.models.goods_receipt import GoodsReceipt, GoodsReceiptLine
from app.repositories.goods_receipt_repository import GoodsReceiptRepository
from app.repositories.purchase_order_repository import PurchaseOrderRepository
from app.schemas.goods_receipt import GoodsReceiptCreate

logger = get_logger(__name__)


class GoodsReceiptService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = GoodsReceiptRepository(session)
        self.po_repository = PurchaseOrderRepository(session)

    async def create_goods_receipt(
        self, payload: GoodsReceiptCreate, *, actor_id: str
    ) -> GoodsReceipt:
        po = await self.po_repository.get_by_id_with_lines(payload.purchase_order_id)
        if po is None:
            raise ValidationError(
                f"Purchase order {payload.purchase_order_id} not found."
            )

        po_lines_by_id = {line.id: line for line in po.lines}
        existing_receipts = await self.repository.list_by_purchase_order(po.id)
        already_received: dict[uuid.UUID, Decimal] = {}
        for receipt in existing_receipts:
            for line in receipt.lines:
                already_received[line.purchase_order_line_id] = already_received.get(
                    line.purchase_order_line_id, Decimal("0")
                ) + line.quantity_received

        for incoming_line in payload.lines:
            po_line = po_lines_by_id.get(incoming_line.purchase_order_line_id)
            if po_line is None:
                raise ValidationError(
                    f"PO line {incoming_line.purchase_order_line_id} does not "
                    f"belong to purchase order {po.id}."
                )
            received_so_far = already_received.get(po_line.id, Decimal("0"))
            outstanding = po_line.quantity_ordered - received_so_far
            if incoming_line.quantity_received > outstanding:
                raise ConflictError(
                    f"Cannot receive {incoming_line.quantity_received} on PO line "
                    f"{po_line.line_number}: only {outstanding} outstanding.",
                    details={
                        "po_line_id": str(po_line.id),
                        "outstanding": str(outstanding),
                        "requested": str(incoming_line.quantity_received),
                    },
                )

        grpo = GoodsReceipt(
            grpo_number=payload.grpo_number,
            purchase_order_id=po.id,
            status=GoodsReceiptStatus.POSTED.value,
            received_date=payload.received_date,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        grpo.lines = [
            GoodsReceiptLine(
                purchase_order_line_id=line.purchase_order_line_id,
                quantity_received=line.quantity_received,
            )
            for line in payload.lines
        ]
        grpo = await self.repository.add(grpo)

        await self._roll_up_po_status(po, po_lines_by_id, already_received, payload)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="goods_receipt.create",
            resource_type="goods_receipt",
            resource_id=str(grpo.id),
            outcome="success",
            metadata={"purchase_order_id": str(po.id)},
        )
        logger.info("goods_receipt_created", grpo_id=str(grpo.id), po_id=str(po.id))
        return grpo

    async def _roll_up_po_status(
        self, po, po_lines_by_id, already_received, payload: GoodsReceiptCreate
    ) -> None:
        """Recompute whether the PO is now partially or fully received
        and persist that status transition."""
        totals_after: dict[uuid.UUID, Decimal] = dict(already_received)
        for line in payload.lines:
            totals_after[line.purchase_order_line_id] = (
                totals_after.get(line.purchase_order_line_id, Decimal("0"))
                + line.quantity_received
            )

        fully_received = all(
            totals_after.get(po_line.id, Decimal("0")) >= po_line.quantity_ordered
            for po_line in po_lines_by_id.values()
        )
        new_status = (
            PurchaseOrderStatus.FULLY_RECEIVED
            if fully_received
            else PurchaseOrderStatus.PARTIALLY_RECEIVED
        )
        await self.po_repository.update(po, status=new_status.value)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
