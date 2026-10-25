"""
app.repositories.bank_statement_line_repository
====================================================
`BankStatementLine` data access, plus the two repositories it needs to
query for match candidates (`OutgoingPayment`/`IncomingPayment`) —
kept together here rather than round-tripping through
`OutgoingPaymentRepository`/`IncomingPaymentRepository` because these
are narrow, matching-specific queries (by amount/reference/date
window), not general CRUD, and belong next to the matching logic they
serve. See `app.services.bank_reconciliation_service` for how these are
combined into an actual candidate list.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.models.bank_statement_line import BankStatementLine
from app.db.models.enums import PaymentStatus
from app.db.models.incoming_payment import IncomingPayment
from app.db.models.payment import OutgoingPayment
from app.repositories.base_repository import BaseRepository

# How far from the statement line's transaction_date to search for a
# same-amount payment when there's no bank_reference to match on
# directly. Wide enough to cover a check that took a while to clear;
# narrow enough that it isn't just "every payment ever". A v1 heuristic
# — see BankReconciliationService's module docstring.
DATE_WINDOW_DAYS = 15


class BankStatementLineRepository(BaseRepository[BankStatementLine]):
    model = BankStatementLine

    async def find_by_reference(
        self, *, bank_reference: str, amount: Decimal
    ) -> OutgoingPayment | IncomingPayment | None:
        """Exact bank_reference match on the appropriate payment table
        for the sign of `amount` (see BankStatementLine.amount's
        docstring). Ignores date entirely — a reference match is a
        strong enough signal on its own; if the amount also differs,
        that's a mismatch worth flagging, not a reason to keep
        searching, so the caller checks amount agreement itself rather
        than this method silently filtering it out."""
        if amount < 0:
            stmt = select(OutgoingPayment).where(
                OutgoingPayment.bank_reference == bank_reference,
                OutgoingPayment.status == PaymentStatus.EXECUTED.value,
            )
        else:
            stmt = select(IncomingPayment).where(
                IncomingPayment.bank_reference == bank_reference
            )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def find_by_amount_and_date_window(
        self, *, amount: Decimal, transaction_date: date
    ) -> list[OutgoingPayment] | list[IncomingPayment]:
        """Same-amount candidates within DATE_WINDOW_DAYS of
        transaction_date, for whichever payment table matches the sign
        of `amount`. Does not exclude already-matched payments — see
        BankReconciliationService for why filtering that happens one
        level up, where both statement-line-side and payment-side
        matched state are visible together."""
        window_start = transaction_date - timedelta(days=DATE_WINDOW_DAYS)
        window_end = transaction_date + timedelta(days=DATE_WINDOW_DAYS)
        magnitude = abs(amount)

        if amount < 0:
            stmt = select(OutgoingPayment).where(
                OutgoingPayment.amount == magnitude,
                OutgoingPayment.status == PaymentStatus.EXECUTED.value,
                OutgoingPayment.executed_date.is_not(None),
                OutgoingPayment.executed_date >= window_start,
                OutgoingPayment.executed_date <= window_end,
            )
        else:
            stmt = select(IncomingPayment).where(
                IncomingPayment.amount == magnitude,
                IncomingPayment.received_date >= window_start,
                IncomingPayment.received_date <= window_end,
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def is_payment_already_matched(
        self, *, payment_type: str, payment_id: uuid.UUID
    ) -> bool:
        """True if some OTHER BankStatementLine already claims this
        payment — a payment should only ever be matched to one
        statement line. Checked by the service before finalizing a
        match, not baked into the candidate queries above, so a
        candidate that's "already taken" can still be surfaced to a
        human as a (lower-confidence) option rather than silently
        vanishing."""
        stmt = select(BankStatementLine.id).where(
            BankStatementLine.is_matched.is_(True),
            BankStatementLine.matched_payment_type == payment_type,
            BankStatementLine.matched_payment_id == payment_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_unmatched(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[BankStatementLine]:
        stmt = self._base_select().where(BankStatementLine.is_matched.is_(False))
        if start_date is not None:
            stmt = stmt.where(BankStatementLine.transaction_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(BankStatementLine.transaction_date <= end_date)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
