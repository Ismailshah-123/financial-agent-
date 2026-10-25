"""add AR module — customers, ar_invoices, ar/ap credit memos

Revision ID: 0002_ar_and_credit_memos
Revises: 0001_initial_schema
Create Date: 2026-08-13

Adds the Accounts Receivable side of the platform: `customers` (the AR
mirror of `vendors`), `ar_invoices` (+lines), `ar_credit_memos`
(+lines), and `ap_credit_memos` (+lines) — the AP-side credit memo that
was also missing from the initial schema. See `app/db/models/customer.py`,
`ar_invoice.py`, and `credit_memo.py` for the full design rationale.

Same hand-written caveat as 0001_initial_schema: run `alembic check`
against a real Postgres instance to confirm no drift before relying on
this in a real deployment.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_ar_and_credit_memos"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # customers
    # ------------------------------------------------------------------
    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tax_id", sa.String(64), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column("address_line", sa.String(500), nullable=True),
        sa.Column("default_currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("credit_limit", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_review"),
        sa.Column("risk_rating", sa.Integer(), nullable=True),
        sa.Column("sap_business_partner_code", sa.String(64), nullable=True),
    )
    op.create_index("ix_customers_name", "customers", ["name"])
    op.create_index("ix_customers_tax_id", "customers", ["tax_id"])
    op.create_index(
        "ix_customers_sap_business_partner_code", "customers", ["sap_business_partner_code"], unique=True
    )

    # ------------------------------------------------------------------
    # ar_invoices
    # ------------------------------------------------------------------
    op.create_table(
        "ar_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invoice_number", sa.String(64), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("sap_doc_entry", sa.Integer(), nullable=True),
    )
    op.create_index("ix_ar_invoices_invoice_number", "ar_invoices", ["invoice_number"])
    op.create_index("ix_ar_invoices_customer_id", "ar_invoices", ["customer_id"])
    op.create_index("ix_ar_invoices_status", "ar_invoices", ["status"])

    # ------------------------------------------------------------------
    # ar_invoice_lines
    # ------------------------------------------------------------------
    op.create_table(
        "ar_invoice_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("ar_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ar_invoices.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("line_total", sa.Numeric(18, 2), nullable=False),
    )
    op.create_index("ix_ar_invoice_lines_ar_invoice_id", "ar_invoice_lines", ["ar_invoice_id"])

    # ------------------------------------------------------------------
    # ar_credit_memos
    # ------------------------------------------------------------------
    op.create_table(
        "ar_credit_memos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("credit_memo_number", sa.String(64), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column(
            "related_ar_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ar_invoices.id"), nullable=True
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("memo_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("sap_doc_entry", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_ar_credit_memos_credit_memo_number", "ar_credit_memos", ["credit_memo_number"], unique=True
    )
    op.create_index("ix_ar_credit_memos_customer_id", "ar_credit_memos", ["customer_id"])
    op.create_index(
        "ix_ar_credit_memos_related_ar_invoice_id", "ar_credit_memos", ["related_ar_invoice_id"]
    )

    # ------------------------------------------------------------------
    # ar_credit_memo_lines
    # ------------------------------------------------------------------
    op.create_table(
        "ar_credit_memo_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "ar_credit_memo_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ar_credit_memos.id"),
            nullable=False,
        ),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("line_total", sa.Numeric(18, 2), nullable=False),
    )
    op.create_index(
        "ix_ar_credit_memo_lines_ar_credit_memo_id", "ar_credit_memo_lines", ["ar_credit_memo_id"]
    )

    # ------------------------------------------------------------------
    # ap_credit_memos
    # ------------------------------------------------------------------
    op.create_table(
        "ap_credit_memos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("credit_memo_number", sa.String(64), nullable=False),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column(
            "related_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("invoices.id"), nullable=True
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("memo_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("sap_doc_entry", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_ap_credit_memos_credit_memo_number", "ap_credit_memos", ["credit_memo_number"], unique=True
    )
    op.create_index("ix_ap_credit_memos_vendor_id", "ap_credit_memos", ["vendor_id"])
    op.create_index("ix_ap_credit_memos_related_invoice_id", "ap_credit_memos", ["related_invoice_id"])

    # ------------------------------------------------------------------
    # ap_credit_memo_lines
    # ------------------------------------------------------------------
    op.create_table(
        "ap_credit_memo_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "ap_credit_memo_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ap_credit_memos.id"),
            nullable=False,
        ),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("line_total", sa.Numeric(18, 2), nullable=False),
    )
    op.create_index(
        "ix_ap_credit_memo_lines_ap_credit_memo_id", "ap_credit_memo_lines", ["ap_credit_memo_id"]
    )


def downgrade() -> None:
    op.drop_table("ap_credit_memo_lines")
    op.drop_table("ap_credit_memos")
    op.drop_table("ar_credit_memo_lines")
    op.drop_table("ar_credit_memos")
    op.drop_table("ar_invoice_lines")
    op.drop_table("ar_invoices")
    op.drop_table("customers")
