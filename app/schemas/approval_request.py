"""
app.schemas.approval_request
================================
Request/response shapes for `app.api.v1.approval_requests` — the
approval inbox API. `ApprovalRequestRead.decision` is the full
serialized `AgentDecision` (see `app.db.models.approval_request`'s
`decision_json` column) — everything a reviewer needs to actually
evaluate the recommendation (reasoning, confidence, supporting
evidence, financial impact) lives there, not duplicated as separate
fields on this schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.schemas.common import APIModel


class ApprovalRequestRead(APIModel):
    id: uuid.UUID
    decision_id: str
    agent_type: str
    correlation_id: str
    actor_id: str
    risk_level: str
    summary: str
    decision: dict[str, Any]
    status: str
    resolved_at: datetime | None
    resolved_by_id: uuid.UUID | None
    resolution_notes: str | None
    action_type: str | None
    action_payload: dict[str, Any]
    idempotency_key: str | None
    execution_status: str
    execution_attempted_at: datetime | None
    executed_at: datetime | None
    execution_result: dict[str, Any] | None
    execution_error: str | None
    created_at: datetime

    @classmethod
    def from_record(cls, record) -> "ApprovalRequestRead":
        """`decision` is exposed under its own name, not the DB
        column's `decision_json` — `model_validate` alone can't do
        that rename, so build it explicitly here."""
        return cls(
            id=record.id,
            decision_id=record.decision_id,
            agent_type=record.agent_type,
            correlation_id=record.correlation_id,
            actor_id=record.actor_id,
            risk_level=record.risk_level,
            summary=record.summary,
            decision=record.decision_json,
            status=record.status,
            resolved_at=record.resolved_at,
            resolved_by_id=record.resolved_by_id,
            resolution_notes=record.resolution_notes,
            action_type=record.action_type,
            action_payload=record.action_payload,
            idempotency_key=record.idempotency_key,
            execution_status=record.execution_status,
            execution_attempted_at=record.execution_attempted_at,
            executed_at=record.executed_at,
            execution_result=record.execution_result,
            execution_error=record.execution_error,
            created_at=record.created_at,
        )


class ApproveRequest(APIModel):
    notes: str | None = None


class RejectRequest(APIModel):
    reason: str


class ApprovalSummaryRead(APIModel):
    """Exact counters for the approval inbox (see `app.services.approval_views`)."""

    pending: int
    awaiting_execution: int
    executing: int
    failed: int
