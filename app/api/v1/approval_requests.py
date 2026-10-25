"""
app.api.v1.approval_requests
================================
The approval inbox API: list pending `ApprovalRequestRecord`s, approve
one, or reject one. See `app.services.approval_service` for the
resolve logic and — importantly — why approving here never applies the
underlying recommendation itself.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query

from app.core.exceptions import BaseAppException, ConflictError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.approval_request import (
    ApprovalRequestRead,
    ApprovalSummaryRead,
    ApproveRequest,
    RejectRequest,
)
from app.services.approval_service import ApprovalService
from app.services.approval_views import ApprovalView

router = APIRouter(prefix="/approval-requests", tags=["approval-requests"])


@router.get("/summary", response_model=ApprovalSummaryRead)
async def approval_summary(
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.APPROVAL_REQUEST_READ)),
) -> ApprovalSummaryRead:
    """Exact inbox counters for badges and dashboards (no row-count cap)."""
    return ApprovalSummaryRead(**await ApprovalService(session).summary())


@router.get("", response_model=list[ApprovalRequestRead])
async def list_pending_approvals(
    agent_type: str | None = Query(default=None),
    view: ApprovalView = Query(
        default="pending",
        description=(
            "Inbox view. 'pending' (default, the historical behaviour) lists requests awaiting a "
            "decision; 'awaiting_execution', 'executing' and 'failed' list approved, executable "
            "requests by execution state so they can be executed or reconciled; 'executed', "
            "'rejected', 'approved' and 'all' provide history."
        ),
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.APPROVAL_REQUEST_READ)),
) -> list[ApprovalRequestRead]:
    service = ApprovalService(session)
    records = await service.list_view(view=view, agent_type=agent_type, offset=offset, limit=limit)
    return [ApprovalRequestRead.from_record(r) for r in records]


@router.post("/{approval_request_id}/approve", response_model=ApprovalRequestRead)
async def approve_request(
    approval_request_id: uuid.UUID,
    payload: ApproveRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.APPROVAL_REQUEST_ACTION)),
) -> ApprovalRequestRead:
    service = ApprovalService(session)
    record = await service.approve(approval_request_id, actor_id=actor.user_id, notes=payload.notes)
    await session.commit()
    return ApprovalRequestRead.from_record(record)


@router.post("/{approval_request_id}/reject", response_model=ApprovalRequestRead)
async def reject_request(
    approval_request_id: uuid.UUID,
    payload: RejectRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.APPROVAL_REQUEST_ACTION)),
) -> ApprovalRequestRead:
    service = ApprovalService(session)
    record = await service.reject(approval_request_id, actor_id=actor.user_id, reason=payload.reason)
    await session.commit()
    return ApprovalRequestRead.from_record(record)


@router.post("/{approval_request_id}/execute", response_model=ApprovalRequestRead)
async def execute_approved_request(
    approval_request_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.APPROVAL_REQUEST_ACTION)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ApprovalRequestRead:
    service = ApprovalService(session)
    existing = await service.repository.get_by_id(approval_request_id)
    if existing is not None and existing.idempotency_key and idempotency_key not in (None, existing.idempotency_key):
        raise ConflictError(
            "The supplied Idempotency-Key does not match this approval action.",
            details={"approval_request_id": str(approval_request_id)},
        )
    try:
        record = await service.execute(approval_request_id, actor_id=actor.user_id, actor_role=actor.role)
    except BaseAppException:
        await session.commit()
        raise
    except Exception:
        await session.commit()
        raise
    await session.commit()
    return ApprovalRequestRead.from_record(record)
