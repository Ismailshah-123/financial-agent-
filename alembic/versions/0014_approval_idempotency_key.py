"""persist stable approval execution idempotency keys"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_approval_idempotency_key"
down_revision: Union[str, None] = "0013_user_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "approval_requests",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE approval_requests "
            "SET idempotency_key = 'approval' || chr(58) || id::text || chr(58) || 'execute' "
            "WHERE action_type IS NOT NULL AND idempotency_key IS NULL"
        )
    )
    op.create_unique_constraint(
        "uq_approval_requests_idempotency_key", "approval_requests", ["idempotency_key"]
    )
    op.create_check_constraint(
        "ck_approval_requests_action_idempotency_pair",
        "approval_requests",
        "(action_type IS NULL AND idempotency_key IS NULL) OR "
        "(action_type IS NOT NULL AND idempotency_key IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_approval_requests_action_idempotency_pair", "approval_requests", type_="check"
    )
    op.drop_constraint(
        "uq_approval_requests_idempotency_key", "approval_requests", type_="unique"
    )
    op.drop_column("approval_requests", "idempotency_key")
