"""
app.api.v1.budgets
======================
Endpoints for creating and reading budgets. See
`app.services.budget_service` for the variance calculation and
`app.api.v1.agents.run_budget_planning_agent` for the AI risk
assessment this API supports but doesn't itself perform.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.budget import BudgetCreate, BudgetRead
from app.services.budget_service import BudgetService

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.post("", response_model=BudgetRead, status_code=201)
async def create_budget(
    payload: BudgetCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.BUDGET_MANAGE)),
) -> BudgetRead:
    service = BudgetService(session)
    budget = await service.create_budget(
        name=payload.name,
        account_code=payload.account_code,
        period_start=payload.period_start,
        period_end=payload.period_end,
        budgeted_amount=payload.budgeted_amount,
        currency=payload.currency,
        notes=payload.notes,
        actor_id=actor.user_id,
    )
    await session.commit()
    return BudgetRead.model_validate(budget)


@router.get("/{budget_id}", response_model=BudgetRead)
async def get_budget(
    budget_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.BUDGET_READ)),
) -> BudgetRead:
    service = BudgetService(session)
    budget = await service.budget_repository.get_by_id_or_raise(budget_id)
    return BudgetRead.model_validate(budget)
