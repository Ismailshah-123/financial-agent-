"""add bank_statement_lines table

Revision ID: 0008_bank_reconciliation
Revises: 0007_period_close
Create Date: 2026-09-10

Adds `bank_statement_lines` — the input side of bank reconciliation:
one row per line item from an external bank statement. Deliberately
NOT a parent `bank_statements` + child `bank_statement_lines` pair:
what's actually reconciled is a set of dated transactions, and a
`statement_label` string (free text, e.g. "Meezan Bank - Sept 2026")
is enough to group them for a human without a full parent entity —
see app.db.models.bank_statement_line's module docstring.

This migration does NOT touch chart_of_accounts, unlike 0006/0007:
bank statement lines aren't journal-entry lines and don't post
anywhere by themselves — see app.services.bank_reconciliation_service's
module docstring for what happens once a line is matched (a human
confirms; nothing is posted automatically).

Same hand-written caveat as the prior migrations: run `alembic check`
against a real Postgres instance to confirm no drift before relying on
this in a real deployment.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_bank_reconciliation"
down_revision: Union[str, None] = "0007_period_close"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bank_statement_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("statement_label", sa.String(255), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column(
            "amount",
            sa.Numeric(18, 2),
            nullable=False,
            comment="Signed: positive = deposit/credit (matches an IncomingPayment), "
            "negative = withdrawal/debit (matches an OutgoingPayment).",
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("bank_reference", sa.String(128), nullable=True),
        sa.Column("is_matched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "matched_payment_type",
            sa.String(16),
            nullable=True,
            comment="'outgoing' or 'incoming' — which payment table matched_payment_id points into.",
        ),
        sa.Column("matched_payment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matched_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_bank_statement_lines_transaction_date",
        "bank_statement_lines",
        ["transaction_date"],
        unique=False,
    )
    op.create_index(
        "ix_bank_statement_lines_is_matched", "bank_statement_lines", ["is_matched"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_bank_statement_lines_is_matched", table_name="bank_statement_lines")
    op.drop_index("ix_bank_statement_lines_transaction_date", table_name="bank_statement_lines")
    op.drop_table("bank_statement_lines")
