"""
app.api.v1.credit_memos
==========================
HTTP endpoints for both AR and AP credit memos. Issuing one
(`POST /credit-memos/ar` or `/ap`) only creates it in DRAFT — applying
it (`/apply`, which posts the journal entry and, for AR, reduces the
related invoice's outstanding balance) requires the elevated
`CREDIT_MEMO_APPROVE` permission, the same approval-gating discipline
as AP invoice approval. See `app.services.credit_memo_service`'s
docstring for why credit memos get this treatment when routine AR
invoice issuance doesn't.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.credit_memo import (
    APCreditMemoCreate,
    APCreditMemoRead,
    ARCreditMemoCreate,
    ARCreditMemoRead,
)
from app.services.credit_memo_service import CreditMemoService

router = APIRouter(prefix="/credit-memos", tags=["credit-memos"])


@router.post("/ar", response_model=ARCreditMemoRead, status_code=status.HTTP_201_CREATED)
async def issue_ar_credit_memo(
    payload: ARCreditMemoCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.CREDIT_MEMO_CREATE)),
) -> ARCreditMemoRead:
    service = CreditMemoService(session)
    memo = await service.issue_ar_credit_memo(payload, actor_id=actor.user_id)
    await session.commit()
    return ARCreditMemoRead.model_validate(memo)


@router.post("/ar/{credit_memo_id}/apply", response_model=ARCreditMemoRead)
async def apply_ar_credit_memo(
    credit_memo_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.CREDIT_MEMO_APPROVE)),
) -> ARCreditMemoRead:
    service = CreditMemoService(session)
    memo = await service.apply_ar_credit_memo(credit_memo_id, actor_id=actor.user_id)
    await session.commit()
    return ARCreditMemoRead.model_validate(memo)


@router.get("/ar/{credit_memo_id}", response_model=ARCreditMemoRead)
async def get_ar_credit_memo(
    credit_memo_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.CREDIT_MEMO_READ)),
) -> ARCreditMemoRead:
    service = CreditMemoService(session)
    memo = await service.ar_repository.get_by_id_with_lines(credit_memo_id)
    if memo is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"AR credit memo {credit_memo_id} not found.")
    return ARCreditMemoRead.model_validate(memo)


@router.post("/ap", response_model=APCreditMemoRead, status_code=status.HTTP_201_CREATED)
async def issue_ap_credit_memo(
    payload: APCreditMemoCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.CREDIT_MEMO_CREATE)),
) -> APCreditMemoRead:
    service = CreditMemoService(session)
    memo = await service.issue_ap_credit_memo(payload, actor_id=actor.user_id)
    await session.commit()
    return APCreditMemoRead.model_validate(memo)


@router.post("/ap/{credit_memo_id}/apply", response_model=APCreditMemoRead)
async def apply_ap_credit_memo(
    credit_memo_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.CREDIT_MEMO_APPROVE)),
) -> APCreditMemoRead:
    service = CreditMemoService(session)
    memo = await service.apply_ap_credit_memo(credit_memo_id, actor_id=actor.user_id)
    await session.commit()
    return APCreditMemoRead.model_validate(memo)


@router.get("/ap/{credit_memo_id}", response_model=APCreditMemoRead)
async def get_ap_credit_memo(
    credit_memo_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.CREDIT_MEMO_READ)),
) -> APCreditMemoRead:
    service = CreditMemoService(session)
    memo = await service.ap_repository.get_by_id_with_lines(credit_memo_id)
    if memo is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"AP credit memo {credit_memo_id} not found.")
    return APCreditMemoRead.model_validate(memo)
