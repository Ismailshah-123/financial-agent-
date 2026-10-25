"""
app.api.v1.period_close
===========================
Endpoints for closing and reopening accounting periods. See
`app.services.period_close_service` for the full workflow and the
validation rules enforced here indirectly (that service raises
`ValidationError`/`ConflictError`/`NotFoundError`, which the app's
exception handlers translate to 400/409/404 — see `app.main`).

`PERIOD_CLOSE_EXECUTE` gates both close and reopen: reopening a period
is at least as consequential as closing one, so it gets the same bar,
not a lower one.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.period_close import ClosePeriodRequest, PeriodCloseRead, ReopenPeriodRequest
from app.services.period_close_service import PeriodCloseService

router = APIRouter(prefix="/period-close", tags=["period-close"])


@router.post("", response_model=PeriodCloseRead, status_code=201)
async def close_period(
    payload: ClosePeriodRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.PERIOD_CLOSE_EXECUTE)),
) -> PeriodCloseRead:
    service = PeriodCloseService(session)
    period_close = await service.close_period(
        start_date=payload.start_date, end_date=payload.end_date, actor_id=actor.user_id
    )
    await session.commit()
    return PeriodCloseRead.model_validate(period_close)


@router.post("/{period_close_id}/reopen", response_model=PeriodCloseRead)
async def reopen_period(
    period_close_id: uuid.UUID,
    payload: ReopenPeriodRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.PERIOD_CLOSE_EXECUTE)),
) -> PeriodCloseRead:
    service = PeriodCloseService(session)
    period_close = await service.reopen_period(
        period_close_id=period_close_id, reason=payload.reason, actor_id=actor.user_id
    )
    await session.commit()
    return PeriodCloseRead.model_validate(period_close)
