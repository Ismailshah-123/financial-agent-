"""
app.api.v1.purchase_orders
=============================
HTTP endpoints for Purchase Orders. `total_amount` is never accepted
from the client (see `app.schemas.purchase_order` docstring) — it's
always the server-computed sum of `lines`, enforced in
`PurchaseOrderService.create_purchase_order`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.purchase_order import PurchaseOrderCreate, PurchaseOrderRead
from app.services.purchase_order_service import PurchaseOrderService

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


@router.post("", response_model=PurchaseOrderRead, status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.PURCHASE_ORDER_CREATE)),
) -> PurchaseOrderRead:
    service = PurchaseOrderService(session)
    po = await service.create_purchase_order(payload, actor_id=actor.user_id)
    await session.commit()
    return PurchaseOrderRead.model_validate(po)


@router.get("/{purchase_order_id}", response_model=PurchaseOrderRead)
async def get_purchase_order(
    purchase_order_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.PURCHASE_ORDER_READ)),
) -> PurchaseOrderRead:
    service = PurchaseOrderService(session)
    po = await service.get_purchase_order(purchase_order_id)
    return PurchaseOrderRead.model_validate(po)


@router.get("/by-vendor/{vendor_id}", response_model=list[PurchaseOrderRead])
async def list_purchase_orders_by_vendor(
    vendor_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.PURCHASE_ORDER_READ)),
) -> list[PurchaseOrderRead]:
    service = PurchaseOrderService(session)
    orders = await service.repository.list_by_vendor(vendor_id)
    return [PurchaseOrderRead.model_validate(po) for po in orders]
