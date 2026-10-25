"""
app.api.v1.payments
======================
HTTP endpoints for Outgoing Payments. `execute_payment` is gated behind
`Permission.PAYMENT_APPROVE` rather than `PAYMENT_INITIATE` — scheduling
a payment and actually sending money are different risk tiers, and only
roles that can approve payments (Finance Director, Approver — see
`app.core.security.ROLE_PERMISSIONS`) can trigger execution. This is a
segregation-of-duties control: whoever scheduled a payment is not
automatically permitted to execute it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.payment import PaymentCreate, PaymentRead
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def schedule_payment(
    payload: PaymentCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.PAYMENT_INITIATE)),
) -> PaymentRead:
    service = PaymentService(session)
    payment = await service.schedule_payment(payload, actor_id=actor.user_id)
    await session.commit()
    return PaymentRead.model_validate(payment)


@router.post("/{payment_id}/execute", response_model=PaymentRead)
async def execute_payment(
    payment_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.PAYMENT_APPROVE)),
) -> PaymentRead:
    service = PaymentService(session)
    payment = await service.execute_payment(payment_id, actor_id=actor.user_id)
    await session.commit()
    return PaymentRead.model_validate(payment)
