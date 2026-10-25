"""
app.db.models.bank_statement_line
=====================================
`BankStatementLine`: one row per line item from an external bank
statement. See `alembic/versions/0008_bank_reconciliation.py` for why
there's no separate parent `BankStatement` entity.

INGESTION IS MANUAL/STRUCTURED INPUT, NOT DOCUMENT AI
-----------------------------------------------------------------
This platform has no OCR/PDF-parsing pipeline (see the project status
doc's "What's NOT Built" section — Document AI is 0%). Ingesting a
statement means POSTing already-structured line data (see
`app.schemas.bank_reconciliation.IngestStatementLinesRequest`) — a
human, or an upstream system that already parsed the PDF/CSV,
provides the data. `BankReconciliationAgent` reasons about lines once
they exist; it doesn't extract them from a document.

MATCHING IS RECORDED HERE, NOT COMPUTED ON READ
-----------------------------------------------------------------
`is_matched`/`matched_payment_type`/`matched_payment_id` persist the
OUTCOME of a confirmed match (see
`BankReconciliationService.confirm_match`) so a reconciliation report
can distinguish "reconciled" from "outstanding" without re-running the
matching logic, and so a previously-confirmed match survives even if
later activity would make the deterministic matcher produce a
different candidate set. `BankReconciliationAgent` only ever
*recommends* a match — same "AI never transacts without approval" rule
as every other agent in this platform; a human (or an explicit
`confirm_match` call) is what actually sets these fields.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import Currency
from app.db.base import AuditMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin


class BankStatementLine(Base, UUIDPrimaryKeyMixin, TimestampMixin, AuditMixin):
    __tablename__ = "bank_statement_lines"

    statement_label: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        doc="Signed: positive = deposit/credit (matches an IncomingPayment), "
        "negative = withdrawal/debit (matches an OutgoingPayment).",
    )
    currency: Mapped[Currency] = mapped_column(String(3), nullable=False)
    bank_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)

    is_matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    matched_payment_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    matched_payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    matched_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<BankStatementLine id={self.id} {self.transaction_date} "
            f"{self.amount} matched={self.is_matched}>"
        )
