"""
app.repositories.goods_receipt_repository
============================================
Goods Receipt (GRPO) data access. `list_by_purchase_order` is what the
AP agent's 3-way match calls to find all receipts posted against a PO
before deciding how much of each line has actually been received.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import selectinload

from app.db.models.goods_receipt import GoodsReceipt
from app.repositories.base_repository import BaseRepository


class GoodsReceiptRepository(BaseRepository[GoodsReceipt]):
    model = GoodsReceipt

    async def list_by_purchase_order(
        self, purchase_order_id: uuid.UUID
    ) -> list[GoodsReceipt]:
        stmt = (
            self._base_select()
            .where(GoodsReceipt.purchase_order_id == purchase_order_id)
            .options(selectinload(GoodsReceipt.lines))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
