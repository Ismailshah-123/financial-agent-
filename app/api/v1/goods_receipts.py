"""
app.api.v1.goods_receipts
============================
HTTP endpoint for posting a Goods Receipt (GRPO) against a Purchase
Order. Over-receipt (claiming more than is outstanding on a PO line) is
rejected by `GoodsReceiptService` with a 409, not silently clamped —
silently clamping would hide a real data-entry error from the person
who made it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.goods_receipt import GoodsReceiptCreate, GoodsReceiptRead
from app.services.goods_receipt_service import GoodsReceiptService

router = APIRouter(prefix="/goods-receipts", tags=["goods-receipts"])


@router.post("", response_model=GoodsReceiptRead, status_code=status.HTTP_201_CREATED)
async def create_goods_receipt(
    payload: GoodsReceiptCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.GOODS_RECEIPT_CREATE)),
) -> GoodsReceiptRead:
    service = GoodsReceiptService(session)
    grpo = await service.create_goods_receipt(payload, actor_id=actor.user_id)
    await session.commit()
    return GoodsReceiptRead.model_validate(grpo)
