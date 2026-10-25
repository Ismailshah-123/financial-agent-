"""
app.schemas.journal_entry
============================
Read-only schemas for Journal Entries. There is deliberately no
`JournalEntryCreate` exposed via the general API in this phase: journal
entries are only ever produced internally by
`app.services.posting_service` (added alongside the AP agent) as a
side effect of invoice approval or payment execution — never accepted
as free-form input from an HTTP caller, which would make the ledger
trivially falsifiable. If/when a manual-journal-entry feature is
required (accountants do sometimes need this), it gets its own
narrowly-scoped, heavily-permissioned endpoint and schema rather than
reusing this one.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.core.constants import Currency, TransactionType
from app.db.models.enums import JournalEntryStatus
from app.schemas.common import APIModel


class JournalEntryLineRead(APIModel):
    id: uuid.UUID
    line_number: int
    account_code: str
    description: str | None
    debit: Decimal
    credit: Decimal


class JournalEntryRead(APIModel):
    id: uuid.UUID
    entry_number: str
    transaction_type: TransactionType
    reference_id: uuid.UUID
    status: JournalEntryStatus
    posting_date: date
    currency: Currency
    total_debit: Decimal
    total_credit: Decimal
    lines: list[JournalEntryLineRead]
