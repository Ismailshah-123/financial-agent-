"""add approval_requests table

Revision ID: 0011_approval_requests
Revises: 0010_fbr_remittance
Create Date: 2026-09-16

Persists `app.agents.schemas.ApprovalRequest` — a fully-specified
Pydantic contract that existed from the very first session (see that
class's docstring: "Created automatically when an
AgentDecision.requires_approval is True. Consumed by the approval-
workflow engine (Phase 2).") but was only ever published as a
transient `AGENT_APPROVAL_REQUIRED` event, never persisted. This
migration — and the `BaseAgent.run()` hook alongside it — is that
Phase 2: every agent, going forward, writes a real row here whenever a
decision needs a human's sign-off, which is what makes an "approval
inbox" (a queue of things actually waiting for someone, not just a
transient event) possible for the first time.

Only decisions with requires_approval=True get a row — this is a
queue of ACTIONABLE items, not a full history of every decision any
agent has ever made. A complete decision log (informational decisions
included) remains a separate, larger undertaking, in the same spirit
as the audit-log persistence gap noted in
alembic/versions/... (see app.core.logging.AuditLogger's docstring and
the project status doc's section on the Compliance Agent).

`decision_json` stores the full serialized AgentDecision (every field:
reasoning, confidence, supporting evidence, rollback strategy, all of
it) so nothing is lost to this table's own narrower indexed columns —
those (agent_type, risk_level, correlation_id) exist for filtering and
sorting an inbox view, not as the source of truth.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_approval_requests"
down_revision: Union[str, None] = "0010_fbr_remittance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("agent_type", sa.String(32), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column(
            "decision_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full serialized AgentDecision — source of truth for everything "
            "not broken out into its own column below.",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
            comment="ApprovalStatus value: pending/approved/rejected/escalated/expired.",
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolution_notes", sa.String(1000), nullable=True),
    )
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"], unique=False)
    op.create_index(
        "ix_approval_requests_agent_type", "approval_requests", ["agent_type"], unique=False
    )
    op.create_index(
        "ix_approval_requests_correlation_id",
        "approval_requests",
        ["correlation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_approval_requests_correlation_id", table_name="approval_requests")
    op.drop_index("ix_approval_requests_agent_type", table_name="approval_requests")
    op.drop_index("ix_approval_requests_status", table_name="approval_requests")
    op.drop_table("approval_requests")
