"""add fbr_remittances table

Revision ID: 0010_fbr_remittance
Revises: 0009_budget_planning
Create Date: 2026-09-14

Adds `fbr_remittances` — one row per payment made TO FBR (Pakistan's
Federal Board of Revenue) for withholding tax collected FROM vendors
during a period. This is the missing half of the withholding tax
story: `PostingService.post_payment_execution` already credits
`DefaultAccounts.WITHHOLDING_TAX_PAYABLE` (2100-WHT) whenever a payment
applies withholding (see that account's docstring — "liability: owed
to the tax authority"), but nothing before this migration recorded
whether that liability was ever actually PAID to FBR. `fbr_remittances`
is that record — see `app.services.fbr_compliance_service` for how it's
compared against the 2100-WHT liability incurred.

Only withholding tax remittance is modeled — not GST/sales tax
remittance, which would need its own liability account and its own
filing cadence this platform doesn't yet track. Documented as a
deliberate v1 scope boundary in that service's module docstring, not a
silent gap.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_fbr_remittance"
down_revision: Union[str, None] = "0009_budget_planning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fbr_remittances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("amount_remitted", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("remitted_date", sa.Date(), nullable=False),
        sa.Column(
            "fbr_reference",
            sa.String(128),
            nullable=False,
            comment="FBR CPR/challan number or equivalent filing reference.",
        ),
        sa.Column("notes", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_fbr_remittances_period_start_end",
        "fbr_remittances",
        ["period_start", "period_end"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_fbr_remittances_period_start_end", table_name="fbr_remittances")
    op.drop_table("fbr_remittances")
