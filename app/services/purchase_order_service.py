"""
app.services.purchase_order_service
======================================
Use-case layer for Purchase Orders. Owns the invariant that
`PurchaseOrder.total_amount` is always the server-computed sum of its
lines (see `app.schemas.purchase_order` docstring) — this is the one
place that sum is calculated, so it can never drift from the lines it's
supposed to represent.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.logging import get_audit_logger, get_logger
from app.db.models.enums import PurchaseOrderStatus
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.repositories.purchase_order_repository import PurchaseOrderRepository
from app.repositories.vendor_repository import VendorRepository
from app.schemas.purchase_order import PurchaseOrderCreate

logger = get_logger(__name__)


class PurchaseOrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = PurchaseOrderRepository(session)
        self.vendor_repository = VendorRepository(session)

    async def create_purchase_order(
        self, payload: PurchaseOrderCreate, *, actor_id: str
    ) -> PurchaseOrder:
        # Confirms the vendor exists (and is not soft-deleted) before we
        # ever create a PO against it — a dangling vendor_id would break
        # every downstream match.
        await self.vendor_repository.get_by_id_or_raise(payload.vendor_id)

        existing = await self.repository.get_by_po_number(payload.po_number)
        if existing is not None:
            raise ConflictError(
                f"A purchase order with number '{payload.po_number}' already exists."
            )

        total_amount: Decimal = sum(
            (line.line_total for line in payload.lines), Decimal("0")
        )

        po = PurchaseOrder(
            po_number=payload.po_number,
            vendor_id=payload.vendor_id,
            status=PurchaseOrderStatus.DRAFT.value,
            currency=payload.currency.value,
            total_amount=total_amount,
            order_date=payload.order_date,
            expected_delivery_date=payload.expected_delivery_date,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        po.lines = [
            PurchaseOrderLine(
                line_number=line.line_number,
                item_code=line.item_code,
                description=line.description,
                quantity_ordered=line.quantity_ordered,
                unit_price=line.unit_price,
                line_total=line.line_total,
            )
            for line in payload.lines
        ]
        po = await self.repository.add(po)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="purchase_order.create",
            resource_type="purchase_order",
            resource_id=str(po.id),
            outcome="success",
            metadata={"po_number": po.po_number, "total_amount": str(total_amount)},
        )
        logger.info(
            "purchase_order_created", po_id=str(po.id), po_number=po.po_number
        )
        return po

    async def get_purchase_order(self, po_id: uuid.UUID) -> PurchaseOrder:
        po = await self.repository.get_by_id_with_lines(po_id)
        if po is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"Purchase order {po_id} not found.")
        return po

    async def mark_status(
        self, po_id: uuid.UUID, status: PurchaseOrderStatus, *, actor_id: str
    ) -> PurchaseOrder:
        po = await self.get_purchase_order(po_id)
        po = await self.repository.update(po, status=status.value)
        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="purchase_order.status_change",
            resource_type="purchase_order",
            resource_id=str(po.id),
            outcome="success",
            metadata={"new_status": status.value},
        )
        return po


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
