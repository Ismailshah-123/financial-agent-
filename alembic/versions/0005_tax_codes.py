"""add tax_codes and seed illustrative Pakistan tax reference data

Revision ID: 0005_tax_codes
Revises: 0004_chart_of_accounts
Create Date: 2026-08-18

Adds `tax_codes` — configurable, effective-dated tax reference data (see
app/db/models/tax_code.py's module docstring for why this is a table
and not a hardcoded constant like DefaultAccounts). Seeds six
illustrative Pakistan codes: federal GST and Sindh Sales Tax on
Services (both SALES_TAX — added on top of a subtotal), plus four
Section 153 withholding-tax codes split by goods/services and
filer/non-filer status (WITHHOLDING_TAX — deducted FROM a payment,
never added to an invoice total; see app/db/models/enums.py's TaxType
docstring for why these are modeled as different mechanisms).

*** EVERY RATE SEEDED BELOW IS ILLUSTRATIVE, NOT VERIFIED-CURRENT.
Confirm against current FBR / Sindh Revenue Board notifications before
relying on this for real tax filings or real payments — same caveat as
app/db/models/tax_code.py's module docstring. ***

tests/integration/conftest.py's `_SEED_TAX_CODES` mirrors this seed
data exactly, since those tests build their schema from live models
rather than by running this migration (see that fixture's docstring).
Keep the two in sync if either changes.

Same hand-written caveat as the prior migrations: run `alembic check`
against a real Postgres instance to confirm no drift before relying on
this in a real deployment.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_tax_codes"
down_revision: Union[str, None] = "0004_chart_of_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (code, name, tax_type, jurisdiction, rate_percent) — mirrors
# tests/integration/conftest.py's _SEED_TAX_CODES exactly.
_SEED_TAX_CODES = [
    ("PK-GST-STD", "Pakistan Federal GST — Standard", "sales_tax", "PK-FEDERAL", "18.000"),
    ("PK-SRB-SERVICES-STD", "Sindh Sales Tax on Services — Standard", "sales_tax", "PK-SINDH", "13.000"),
    ("PK-WHT-153-GOODS-FILER", "Withholding — Goods, Filer", "withholding_tax", "PK-FEDERAL", "4.000"),
    ("PK-WHT-153-GOODS-NONFILER", "Withholding — Goods, Non-Filer", "withholding_tax", "PK-FEDERAL", "8.000"),
    ("PK-WHT-153-SERVICES-FILER", "Withholding — Services, Filer", "withholding_tax", "PK-FEDERAL", "8.000"),
    ("PK-WHT-153-SERVICES-NONFILER", "Withholding — Services, Non-Filer", "withholding_tax", "PK-FEDERAL", "16.000"),
]
_SEED_EFFECTIVE_FROM = date(2020, 1, 1)


def upgrade() -> None:
    op.create_table(
        "tax_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tax_type", sa.String(20), nullable=False),
        sa.Column("jurisdiction", sa.String(32), nullable=False),
        sa.Column("rate_percent", sa.Numeric(6, 3), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.String(500), nullable=True),
    )
    op.create_index("ix_tax_codes_code", "tax_codes", ["code"], unique=False)

    tax_codes_table = sa.table(
        "tax_codes",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("tax_type", sa.String),
        sa.column("jurisdiction", sa.String),
        sa.column("rate_percent", sa.Numeric),
        sa.column("effective_from", sa.Date),
        sa.column("effective_to", sa.Date),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        tax_codes_table,
        [
            {
                "id": uuid.uuid4(),
                "code": code,
                "name": name,
                "tax_type": tax_type,
                "jurisdiction": jurisdiction,
                "rate_percent": rate_percent,
                "effective_from": _SEED_EFFECTIVE_FROM,
                "effective_to": None,
                "is_active": True,
            }
            for code, name, tax_type, jurisdiction, rate_percent in _SEED_TAX_CODES
        ],
    )


def downgrade() -> None:
    op.drop_table("tax_codes")
