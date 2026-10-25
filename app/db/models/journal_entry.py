"""
app.db.models.journal_entry
=============================
`JournalEntry` + `JournalEntryLine`: the General Ledger posting produced
when an invoice is approved (debit expense/asset, credit accounts
payable) or a payment executes (debit accounts payable, credit cash).
Every other finance module (Reporting, Budget, Audit) ultimately reads
from journal entries, so this model is deliberately generic
(`transaction_type` + `reference_id` link back to whichever document
caused the posting) rather than having a separate ledger table per
source document type.

INVARIANT: a posted journal entry's debits must equal its credits. This
is enforced in the service layer (`app.services`, next phase) at the
point of posting — not with a DB CHECK constraint referencing SUM() over
child rows, which SQLAlchemy/Postgres can't express declaratively without
a trigger. A migration-level trigger is a reasonable Phase 1.x hardening
step once the posting service exists and this invariant has real
integration-test coverage.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Currency, TransactionType
from app.db.base import AuditMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import JournalEntryStatus


class JournalEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin, AuditMixin):
    __tablename__ = "journal_entries"

    entry_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    transaction_type: Mapped[TransactionType] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        doc="Id of the source document (Invoice.id, OutgoingPayment.id, ...). "
        "Polymorphic by design — see transaction_type for how to interpret it.",
    )

    status: Mapped[JournalEntryStatus] = mapped_column(
        String(16), nullable=False, default=JournalEntryStatus.DRAFT.value
    )
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[Currency] = mapped_column(String(3), nullable=False)
    total_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    sap_doc_entry: Mapped[int | None] = mapped_column(nullable=True)

    lines: Mapped[list["JournalEntryLine"]] = relationship(
        back_populates="journal_entry", cascade="all, delete-orphan", order_by="JournalEntryLine.line_number"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<JournalEntry id={self.id} entry_number={self.entry_number!r} status={self.status}>"


class JournalEntryLine(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "journal_entry_lines"

    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    account_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    journal_entry: Mapped["JournalEntry"] = relationship(back_populates="lines")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<JournalEntryLine entry={self.journal_entry_id} line={self.line_number}>"
