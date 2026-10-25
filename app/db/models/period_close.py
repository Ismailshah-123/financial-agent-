"""
app.db.models.period_close
=============================
`PeriodClose`: one row per closed accounting period. See
`alembic/versions/0007_period_close.py` for why this stores a snapshot
(`total_revenue`/`total_expense`/`net_income`) rather than relying on
re-querying the ledger, and `app.services.period_close_service` for the
full close/reopen workflow this row is the audit trail for.

`is_reopened` + the `reopened_*`/`reopening_journal_entry_id` fields
exist because "we closed the wrong range" is a realistic mistake, and
this codebase's convention (see every `AgentDecision.rollback_strategy`)
is that financial actions should have a documented way back. Reopening
never deletes or edits the original closing journal entry — it posts a
new REVERSING entry (debits and credits swapped) and marks this row,
preserving a complete, honest audit trail of both the mistake and its
correction. See `PeriodCloseService.reopen_period`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin


class PeriodClose(Base, UUIDPrimaryKeyMixin, TimestampMixin, AuditMixin):
    __tablename__ = "period_closes"

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    closing_journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"), nullable=False
    )

    # Snapshot at close time — see module docstring for why this isn't
    # just re-derived from the ledger on read.
    total_revenue: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_expense: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    net_income: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    is_reopened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reopen_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reopening_journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<PeriodClose id={self.id} {self.start_date}..{self.end_date} "
            f"net_income={self.net_income} reopened={self.is_reopened}>"
        )
