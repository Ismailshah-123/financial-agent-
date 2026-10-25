"""add filer_status to vendors, withholding fields to outgoing_payments, seed WHT payable account

Revision ID: 0006_withholding_tax
Revises: 0005_tax_codes
Create Date: 2026-08-20

Wires withholding tax into the payment flow:
  - vendors.filer_status: drives which Section-153-style withholding
    rate applies (see app.db.models.enums.FilerStatus).
  - outgoing_payments.withholding_tax_code / withholding_tax_amount:
    what was withheld and under which TaxCode, if any (see
    app.db.models.payment.OutgoingPayment).
  - A new chart_of_accounts row, 2100-WHT (Withholding Tax Payable,
    liability) — PostingService.post_payment_execution posts to this
    account for the withheld portion of a payment. Without this row,
    FinancialReportingService would raise the moment a withheld payment
    is posted (its "every posted account must be in the chart of
    accounts" invariant — see that service's docstring).

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

revision: str = "0006_withholding_tax"
down_revision: Union[str, None] = "0005_tax_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("vendors", sa.Column("filer_status", sa.String(16), nullable=True))

    op.add_column(
        "outgoing_payments", sa.Column("withholding_tax_code", sa.String(64), nullable=True)
    )
    op.add_column(
        "outgoing_payments",
        sa.Column(
            "withholding_tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"
        ),
    )

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
                "account_code": "2100-WHT",
                "account_name": "Withholding Tax Payable",
                "account_type": "liability",
                "is_contra": False,
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM chart_of_accounts WHERE account_code = '2100-WHT'")
    op.drop_column("outgoing_payments", "withholding_tax_amount")
    op.drop_column("outgoing_payments", "withholding_tax_code")
    op.drop_column("vendors", "filer_status")
