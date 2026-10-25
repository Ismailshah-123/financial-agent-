"""
app.repositories.journal_entry_repository
============================================
Journal Entry data access. `list_by_reference` is how any module
(reporting, audit) traces every ledger posting back to its source
document (an invoice approval, a payment execution) given
`transaction_type` + `reference_id` — see the polymorphic design note
in `app.db.models.journal_entry`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import selectinload

from app.core.constants import TransactionType
from app.db.models.journal_entry import JournalEntry
from app.repositories.base_repository import BaseRepository


class JournalEntryRepository(BaseRepository[JournalEntry]):
    model = JournalEntry

    async def get_by_id_with_lines(self, id_: uuid.UUID) -> JournalEntry | None:
        stmt = (
            self._base_select()
            .where(JournalEntry.id == id_)
            .options(selectinload(JournalEntry.lines))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_reference(
        self, *, transaction_type: TransactionType, reference_id: uuid.UUID
    ) -> list[JournalEntry]:
        stmt = self._base_select().where(
            JournalEntry.transaction_type == transaction_type.value,
            JournalEntry.reference_id == reference_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
