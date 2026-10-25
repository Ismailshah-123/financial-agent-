"""add chart_of_accounts and seed default accounts

Revision ID: 0004_chart_of_accounts
Revises: 0003_incoming_payments
Create Date: 2026-08-17

Adds `chart_of_accounts` and seeds it with every account code
`app.services.posting_service.DefaultAccounts` already posts journal
entries to. Without this seed data, `FinancialReportingService` would
raise on its very first report — see that service's docstring on why a
posted account with no chart-of-accounts row is a loud failure, not a
silent omission.

UUIDs for the seed rows are generated in Python (uuid.uuid4()), not via
Postgres's gen_random_uuid(), since that function requires the pgcrypto
extension to be enabled and this migration shouldn't assume that.

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

revision: str = "0004_chart_of_accounts"
down_revision: Union[str, None] = "0003_incoming_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (account_code, account_name, account_type, is_contra) — mirrors
# DefaultAccounts in app/services/posting_service.py exactly.
_SEED_ACCOUNTS = [
    ("1000-CASH", "Cash", "asset", False),
    ("1100-AR", "Accounts Receivable", "asset", False),
    ("2000-AP", "Accounts Payable", "liability", False),
    ("4000-REV", "Revenue", "revenue", False),
    ("5000-EXP", "General Expense", "expense", False),
    ("5100-PURRET", "Purchase Returns", "expense", True),
]


def upgrade() -> None:
    op.create_table(
        "chart_of_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("account_code", sa.String(32), nullable=False),
        sa.Column("account_name", sa.String(255), nullable=False),
        sa.Column("account_type", sa.String(16), nullable=False),
        sa.Column("is_contra", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_chart_of_accounts_account_code", "chart_of_accounts", ["account_code"], unique=True)

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
                "account_code": code,
                "account_name": name,
                "account_type": account_type,
                "is_contra": is_contra,
                "is_active": True,
            }
            for code, name, account_type, is_contra in _SEED_ACCOUNTS
        ],
    )


def downgrade() -> None:
    op.drop_table("chart_of_accounts")
