"""
app.db.models.approval_request
==================================
`ApprovalRequestRecord`: the persisted form of
`app.agents.schemas.ApprovalRequest`. See
`alembic/versions/0011_approval_requests.py` for why this exists now
and why only `requires_approval=True` decisions get a row here.

Written by `BaseAgent.run()` itself (see that class's `_persist_approval_requests`),
not by any individual agent — every agent gets this for free, the same
way every agent gets permission-checking and event publishing for
free, because it lives in the one place all of them funnel through.

`decision_json` is the full serialized `AgentDecision` — everything
else on this row is a narrower, indexed projection of it for filtering
an inbox view, not a separate source of truth.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ApprovalRequestRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "approval_requests"

    decision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    decision_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    action_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    execution_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_applicable"
    )
    execution_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    execution_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ApprovalRequestRecord id={self.id} agent_type={self.agent_type} "
            f"status={self.status} risk={self.risk_level}>"
        )
