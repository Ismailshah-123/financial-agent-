"""Auditor-facing durable audit log APIs."""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.models.audit_log import AuditChainState, AuditLog
from app.db.session import get_db
from app.repositories.audit_log_repository import AuditLogRepository
from app.schemas.audit_log import AuditLogRead, AuditLogVerifyRead
from app.schemas.common import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/audit", tags=["audit"])


def _canonical_payload(row: AuditLog) -> dict[str, object]:
    return {
        "entry_id": str(row.id),
        "sequence_number": row.sequence_number,
        "timestamp": row.created_at.isoformat(),
        "correlation_id": row.correlation_id,
        "actor_id": row.actor_id,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "outcome": row.outcome,
        "metadata": row.metadata_json,
        "prev_hash": row.prev_hash,
    }


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


@router.get("/logs", response_model=PaginatedResponse[AuditLogRead])
async def list_audit_logs(
    actor_id: str | None = Query(default=None, max_length=64),
    action: str | None = Query(default=None, max_length=128),
    resource_type: str | None = Query(default=None, max_length=64),
    resource_id: str | None = Query(default=None, max_length=128),
    outcome: str | None = Query(default=None, max_length=32),
    pagination: PaginationParams = Depends(),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AUDIT_LOG_READ)),
) -> PaginatedResponse[AuditLogRead]:
    records, total = await AuditLogRepository(session).list_logs(
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    return PaginatedResponse[AuditLogRead](
        items=[AuditLogRead.from_record(record) for record in records],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/verify", response_model=AuditLogVerifyRead)
async def verify_audit_chain(
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AUDIT_LOG_READ)),
) -> AuditLogVerifyRead:
    records = await AuditLogRepository(session).list_chain()
    previous = "0" * 64
    for index, row in enumerate(records):
        if row.prev_hash != previous:
            return AuditLogVerifyRead(
                valid=False,
                checked_entries=index,
                first_failure_sequence=row.sequence_number,
                message="Audit chain continuity check failed.",
            )
        computed = _hash_payload(_canonical_payload(row))
        if computed != row.entry_hash:
            return AuditLogVerifyRead(
                valid=False,
                checked_entries=index + 1,
                first_failure_sequence=row.sequence_number,
                message="Audit entry hash verification failed.",
            )
        previous = row.entry_hash

    state = await session.scalar(select(AuditChainState).where(AuditChainState.id == "global"))
    if state is None or state.last_hash != previous:
        return AuditLogVerifyRead(
            valid=False,
            checked_entries=len(records),
            message="Audit chain state does not match the final durable entry.",
        )
    return AuditLogVerifyRead(
        valid=True,
        checked_entries=len(records),
        message="Audit chain verified successfully.",
    )
