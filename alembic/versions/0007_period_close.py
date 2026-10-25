"""add period_closes table, seed 3000-RE retained earnings account

Revision ID: 0007_period_close
Revises: 0006_withholding_tax
Create Date: 2026-09-08

Adds what closes the gap FinancialReportingService's module docstring
flags explicitly: "this platform doesn't model a period-close process
... so [the Balance Sheet's equity] number is directionally correct
but is a live computation, not a posted balance."

  - A new chart_of_accounts row, 3000-RE (Retained Earnings, EQUITY,
    credit-normal) — the first EQUITY-typed account this platform has
    ever seeded (see that model's docstring: "there are none seeded by
    default", now out of date as of this migration).
  - `period_closes`: one row per closed period. Deliberately stores a
    SNAPSHOT (total_revenue, total_expense, net_income) alongside the
    FK to the closing journal entry — not because the ledger can't be
    re-queried, but because once a period closes, its own revenue/
    expense accounts net back to zero in any later cumulative query
    (see app.services.period_close_service's module docstring for why
    that's correct, not a bug) — so the snapshot is the only place
    that period's real P&L figures still live in an obviously-readable
    form.

WHY NO DB-LEVEL LOCK PREVENTING POSTS INTO A CLOSED PERIOD
------------------------------------------------------------------
The period-lock invariant (no new journal entry may post with a date
inside an already-closed range) is enforced in PostingService.post()
— the single place every journal entry already flows through — rather
than with a trigger or CHECK constraint here, for the same reason the
debit=credit invariant isn't a DB constraint either (see
journal_entry.py's own docstring): the check needs to query another
table (period_closes) at insert time, which Postgres CHECK constraints
can't do without a trigger, and this codebase's convention is
service-layer enforcement over triggers until there's a specific
reason to harden further.

Same hand-written caveat as the prior migrations: run `alembic check`
against a real Postgres instance to confirm no drift before relying on
this in a real deployment.
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_period_close"
down_revision: Union[str, None] = "0006_withholding_tax"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    chart_of_accounts_table = sa.table(
        "chart_of_accounts",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("account_code", sa.String),
        sa.column("account_name", sa.String),
        sa.column("account_type", sa.String),
        sa.column("is_contra", sa.Boolean),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        chart_of_accounts_table,
        [
            {
                "id": uuid.uuid4(),
                "account_code": "3000-RE",
                "account_name": "Retained Earnings",
                "account_type": "equity",
                "is_contra": False,
                "is_active": True,
            }
        ],
    )

    op.create_table(
        "period_closes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "closing_journal_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journal_entries.id"),
            nullable=False,
        ),
        sa.Column("total_revenue", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_expense", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_income", sa.Numeric(18, 2), nullable=False),
        sa.Column("is_reopened", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reopen_reason", sa.String(500), nullable=True),
        sa.Column(
            "reopening_journal_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journal_entries.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_period_closes_start_end", "period_closes", ["start_date", "end_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_period_closes_start_end", table_name="period_closes")
    op.drop_table("period_closes")
    op.execute("DELETE FROM chart_of_accounts WHERE account_code = '3000-RE'")
