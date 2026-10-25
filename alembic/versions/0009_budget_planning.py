"""add budgets table

Revision ID: 0009_budget_planning
Revises: 0008_bank_reconciliation
Create Date: 2026-09-13

Adds `budgets` — one row per (account_code, period) spending or revenue
target. References `chart_of_accounts` by `account_code` (a string),
not a foreign key to its UUID id — same pattern `tax_codes` and
`period_closes` use for account references, matching
`DefaultAccounts`' string-code convention throughout this codebase
rather than introducing the only account FK in the schema for this one
table.

No chart_of_accounts changes here — a Budget doesn't post anything; it
never becomes a journal entry, so there's no new account needed (unlike
0007's Retained Earnings addition).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_budget_planning"
down_revision: Union[str, None] = "0008_bank_reconciliation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("account_code", sa.String(64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("budgeted_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
    )
    op.create_index("ix_budgets_account_code", "budgets", ["account_code"], unique=False)
    op.create_index(
        "ix_budgets_period_start_end", "budgets", ["period_start", "period_end"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_budgets_period_start_end", table_name="budgets")
    op.drop_index("ix_budgets_account_code", table_name="budgets")
    op.drop_table("budgets")
