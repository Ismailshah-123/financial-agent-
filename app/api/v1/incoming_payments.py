"""
app.api.v1.incoming_payments
===============================
HTTP endpoint for recording customer payments. Uses the same
`PAYMENT_INITIATE` permission as the AP side's outgoing payments (the
`AR_CLERK` role already carries it) rather than a new AR-specific
permission — recording that cash was received is conceptually the same
class of action as scheduling an outgoing payment: a routine part of
the AR/AP clerk's job, not something requiring elevated approval the
way executing an outgoing payment or applying a credit memo does.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.incoming_payment import IncomingPaymentCreate, IncomingPaymentRead
from app.services.incoming_payment_service import IncomingPaymentService

router = APIRouter(prefix="/incoming-payments", tags=["incoming-payments"])


@router.post("", response_model=IncomingPaymentRead, status_code=status.HTTP_201_CREATED)
async def record_incoming_payment(
    payload: IncomingPaymentCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.PAYMENT_INITIATE)),
) -> IncomingPaymentRead:
    service = IncomingPaymentService(session)
    payment = await service.record_payment(payload, actor_id=actor.user_id)
    await session.commit()
    return IncomingPaymentRead.model_validate(payment)
