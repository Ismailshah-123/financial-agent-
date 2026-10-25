"""add incoming_payments and ar_invoices.amount_credited

Revision ID: 0003_incoming_payments
Revises: 0002_ar_and_credit_memos
Create Date: 2026-08-14

Adds `incoming_payments` (the AR mirror of `outgoing_payments`) and a
new `amount_credited` column on `ar_invoices`, splitting what was
previously a single `amount_paid` running total into two: cash received
(`amount_paid`, moved only by IncomingPaymentService) and credit memos
applied (`amount_credited`, moved only by CreditMemoService). See
`app/services/ar_invoice_service.py`'s `compute_ar_invoice_status` and
`apply_balance_change` for how the two are combined to determine
outstanding balance and status.

Same hand-written caveat as the prior migrations: run `alembic check`
against a real Postgres instance to confirm no drift before relying on
this in a real deployment.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_incoming_payments"
down_revision: Union[str, None] = "0002_ar_and_credit_memos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # ar_invoices.amount_credited — new column, backfilled to 0
    # ------------------------------------------------------------------
    op.add_column(
        "ar_invoices",
        sa.Column("amount_credited", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )

    # ------------------------------------------------------------------
    # incoming_payments
    # ------------------------------------------------------------------
    op.create_table(
        "incoming_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payment_number", sa.String(64), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column(
            "ar_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ar_invoices.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="executed"),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("payment_method", sa.String(32), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("bank_reference", sa.String(128), nullable=True),
        sa.Column("sap_doc_entry", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_incoming_payments_payment_number", "incoming_payments", ["payment_number"], unique=True
    )
    op.create_index("ix_incoming_payments_customer_id", "incoming_payments", ["customer_id"])
    op.create_index("ix_incoming_payments_ar_invoice_id", "incoming_payments", ["ar_invoice_id"])
    op.create_index("ix_incoming_payments_status", "incoming_payments", ["status"])


def downgrade() -> None:
    op.drop_table("incoming_payments")
    op.drop_column("ar_invoices", "amount_credited")
