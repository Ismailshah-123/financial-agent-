"""
app.repositories.purchase_order_repository
=============================================
Purchase Order data access. `get_by_id_with_lines` eagerly loads
`.lines` via `selectinload` — the AP agent's matching logic always needs
line-level detail, so this avoids N+1 queries or lazy-load-in-async
errors (SQLAlchemy async sessions cannot implicitly lazy-load once the
session context has moved on, so eager loading isn't just an
optimization here, it's a correctness requirement).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.purchase_order import PurchaseOrder
from app.repositories.base_repository import BaseRepository


class PurchaseOrderRepository(BaseRepository[PurchaseOrder]):
    model = PurchaseOrder

    async def get_by_id_with_lines(self, id_: uuid.UUID) -> PurchaseOrder | None:
        stmt = (
            self._base_select()
            .where(PurchaseOrder.id == id_)
            .options(selectinload(PurchaseOrder.lines))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    async def get_by_id_with_lines_for_update(self, id_: uuid.UUID) -> PurchaseOrder | None:
        stmt = (
            self._base_select()
            .where(PurchaseOrder.id == id_)
            .with_for_update().options(selectinload(PurchaseOrder.lines))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_po_number(self, po_number: str) -> PurchaseOrder | None:
        stmt = self._base_select().where(PurchaseOrder.po_number == po_number)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_vendor(
        self, vendor_id: uuid.UUID, *, offset: int = 0, limit: int = 25
    ) -> list[PurchaseOrder]:
        stmt = (
            self._base_select()
            .where(PurchaseOrder.vendor_id == vendor_id)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
