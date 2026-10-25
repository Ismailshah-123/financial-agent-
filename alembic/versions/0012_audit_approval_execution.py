"""add durable audit log and typed approval execution state

Revision ID: 0012_audit_approval_execution
Revises: 0011_approval_requests
Create Date: 2026-10-09

Adds a durable append-only audit stream with database-enforced immutability and
hash-chain state, plus explicit approval action/execution fields. Approval
resolution and financial execution remain separate lifecycle transitions.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_audit_approval_execution"
down_revision: Union[str, None] = "0011_approval_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SEQUENCE audit_log_sequence START WITH 1 INCREMENT BY 1"))
    op.create_table(
        "audit_chain_state",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("last_hash", sa.String(length=64), nullable=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO audit_chain_state (id, last_hash) VALUES ('global', "
            "'0000000000000000000000000000000000000000000000000000000000000000')"
        )
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sequence_number", sa.BigInteger(), nullable=False, unique=True, server_default=sa.text("nextval('audit_log_sequence')")),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("entry_hash", sa.String(length=64), nullable=False, unique=True),
    )
    for name, columns in {
        "ix_audit_logs_sequence_number": ["sequence_number"],
        "ix_audit_logs_actor_id": ["actor_id"],
        "ix_audit_logs_action": ["action"],
        "ix_audit_logs_resource_type": ["resource_type"],
        "ix_audit_logs_resource_id": ["resource_id"],
        "ix_audit_logs_outcome": ["outcome"],
        "ix_audit_logs_correlation_id": ["correlation_id"],
    }.items():
        op.create_index(name, "audit_logs", columns, unique=False)

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION prevent_audit_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_logs is append-only; UPDATE and DELETE are prohibited';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER audit_logs_immutable BEFORE UPDATE OR DELETE ON audit_logs "
            "FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation()"
        )
    )

    op.add_column("approval_requests", sa.Column("action_type", sa.String(length=64), nullable=True))
    op.add_column(
        "approval_requests",
        sa.Column("action_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "approval_requests", sa.Column("execution_status", sa.String(length=32), nullable=False, server_default="not_applicable")
    )
    op.add_column("approval_requests", sa.Column("execution_attempted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("approval_requests", sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "approval_requests",
        sa.Column("execution_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("approval_requests", sa.Column("execution_error", sa.String(length=1000), nullable=True))
    op.create_index("ix_approval_requests_action_type", "approval_requests", ["action_type"], unique=False)
    op.create_index("ix_approval_requests_execution_status", "approval_requests", ["execution_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_approval_requests_execution_status", table_name="approval_requests")
    op.drop_index("ix_approval_requests_action_type", table_name="approval_requests")
    op.drop_column("approval_requests", "execution_error")
    op.drop_column("approval_requests", "execution_result")
    op.drop_column("approval_requests", "executed_at")
    op.drop_column("approval_requests", "execution_attempted_at")
    op.drop_column("approval_requests", "execution_status")
    op.drop_column("approval_requests", "action_payload")
    op.drop_column("approval_requests", "action_type")

    op.execute(sa.text("DROP TRIGGER IF EXISTS audit_logs_immutable ON audit_logs"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_audit_mutation()"))
    for name in [
        "ix_audit_logs_correlation_id",
        "ix_audit_logs_outcome",
        "ix_audit_logs_resource_id",
        "ix_audit_logs_resource_type",
        "ix_audit_logs_action",
        "ix_audit_logs_actor_id",
        "ix_audit_logs_sequence_number",
    ]:
        op.drop_index(name, table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("audit_chain_state")
    op.execute(sa.text("DROP SEQUENCE IF EXISTS audit_log_sequence"))
