"""
app.services.bank_reconciliation_service
============================================
Deterministic core for bank reconciliation: ingesting statement lines,
finding match candidates against `OutgoingPayment`/`IncomingPayment`,
and confirming a match once a human (or `BankReconciliationAgent`'s
recommendation, once approved) picks one.

TWO-TIER MATCHING STRATEGY
---------------------------------
1. **By `bank_reference`**, when the statement line has one: a bank
   reference match is treated as authoritative — if found, that's the
   only candidate returned, even if the amount doesn't quite agree
   (which becomes a `reference_amount_mismatch`, a HIGH-risk anomaly
   for `BankReconciliationAgent` to flag, not a reason to keep
   searching for a better match).
2. **By amount + a `DATE_WINDOW_DAYS`-wide date window**, when there's
   no reference or no reference match: weaker signal, so ALL
   candidates in the window are returned rather than picking one —
   disambiguating among several same-amount payments is exactly what
   `BankReconciliationAgent` uses an LLM for for (reasoning over
   description text), not something this deterministic layer decides.

WHY A PAYMENT'S "ALREADY MATCHED" STATE ISN'T EXCLUDED FROM CANDIDATES
------------------------------------------------------------------------------
`is_payment_already_matched` is exposed on each `MatchCandidate` rather
than used to filter the query, so a human reviewing an ambiguous case
can still see "this one's already claimed by another line" as context
— useful when a previous match might have been wrong — rather than
that option just silently disappearing. `confirm_match` DOES enforce
it as a hard rule: a payment can only ever be matched to one line.

WHAT THIS SERVICE NEVER DOES
------------------------------------
Never posts a journal entry, never mutates `OutgoingPayment`/
`IncomingPayment`. Confirming a match only sets fields on the
`BankStatementLine` row itself. If a statement line has NO candidate
(a bank fee nobody recorded, for instance),
`BankReconciliationAgent` may recommend creating a new journal entry
for it — that recommendation, if accepted, goes through
`PostingService` like everything else; this service has no opinion on
it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Currency
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.db.models.bank_statement_line import BankStatementLine
from app.repositories.bank_statement_line_repository import BankStatementLineRepository

logger = get_logger(__name__)


@dataclass(frozen=True)
class StatementLineInput:
    transaction_date: date
    description: str
    amount: Decimal
    currency: Currency
    bank_reference: str | None = None


@dataclass(frozen=True)
class MatchCandidate:
    payment_type: str  # "outgoing" | "incoming"
    payment_id: uuid.UUID
    payment_amount: Decimal
    payment_date: date
    payment_reference: str | None
    match_reason: str  # "reference_and_amount" | "reference_amount_mismatch" | "amount_and_date"
    already_matched_elsewhere: bool


class BankReconciliationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = BankStatementLineRepository(session)

    async def ingest_statement_lines(
        self, *, statement_label: str, lines: list[StatementLineInput], actor_id: str
    ) -> list[BankStatementLine]:
        if not lines:
            raise ValidationError("At least one statement line is required.")

        created: list[BankStatementLine] = []
        creator_id = uuid.UUID(actor_id) if _is_uuid(actor_id) else None
        for line_input in lines:
            statement_line = BankStatementLine(
                statement_label=statement_label,
                transaction_date=line_input.transaction_date,
                description=line_input.description,
                amount=line_input.amount,
                currency=line_input.currency,
                bank_reference=line_input.bank_reference,
                created_by_id=creator_id,
            )
            created.append(await self.repository.add(statement_line))

        logger.info(
            "bank_statement_lines_ingested",
            statement_label=statement_label,
            count=len(created),
        )
        return created

    async def find_candidates(self, statement_line: BankStatementLine) -> list[MatchCandidate]:
        payment_type = "outgoing" if statement_line.amount < 0 else "incoming"

        if statement_line.bank_reference:
            reference_match = await self.repository.find_by_reference(
                bank_reference=statement_line.bank_reference, amount=statement_line.amount
            )
            if reference_match is not None:
                already_taken = await self.repository.is_payment_already_matched(
                    payment_type=payment_type, payment_id=reference_match.id
                )
                amounts_agree = reference_match.amount == abs(statement_line.amount)
                return [
                    MatchCandidate(
                        payment_type=payment_type,
                        payment_id=reference_match.id,
                        payment_amount=reference_match.amount,
                        payment_date=_payment_date(reference_match, payment_type),
                        payment_reference=reference_match.bank_reference,
                        match_reason=(
                            "reference_and_amount"
                            if amounts_agree
                            else "reference_amount_mismatch"
                        ),
                        already_matched_elsewhere=already_taken,
                    )
                ]

        amount_matches = await self.repository.find_by_amount_and_date_window(
            amount=statement_line.amount, transaction_date=statement_line.transaction_date
        )
        candidates = []
        for payment in amount_matches:
            already_taken = await self.repository.is_payment_already_matched(
                payment_type=payment_type, payment_id=payment.id
            )
            candidates.append(
                MatchCandidate(
                    payment_type=payment_type,
                    payment_id=payment.id,
                    payment_amount=payment.amount,
                    payment_date=_payment_date(payment, payment_type),
                    payment_reference=payment.bank_reference,
                    match_reason="amount_and_date",
                    already_matched_elsewhere=already_taken,
                )
            )
        return candidates

    async def confirm_match(
        self,
        *,
        statement_line_id: uuid.UUID,
        payment_type: str,
        payment_id: uuid.UUID,
        actor_id: str,
    ) -> BankStatementLine:
        if payment_type not in ("outgoing", "incoming"):
            raise ValidationError("payment_type must be 'outgoing' or 'incoming'.")

        statement_line = await self.repository.get_by_id(statement_line_id)
        if statement_line is None:
            raise NotFoundError(
                f"BankStatementLine with id {statement_line_id} not found.",
                details={"model": "BankStatementLine", "id": str(statement_line_id)},
            )
        if statement_line.is_matched:
            raise ConflictError(
                f"BankStatementLine {statement_line_id} is already matched to a "
                f"{statement_line.matched_payment_type} payment "
                f"({statement_line.matched_payment_id}).",
                details={"statement_line_id": str(statement_line_id)},
            )

        already_taken = await self.repository.is_payment_already_matched(
            payment_type=payment_type, payment_id=payment_id
        )
        if already_taken:
            raise ConflictError(
                f"This {payment_type} payment is already matched to a different "
                f"statement line.",
                details={"payment_type": payment_type, "payment_id": str(payment_id)},
            )

        statement_line.is_matched = True
        statement_line.matched_payment_type = payment_type
        statement_line.matched_payment_id = payment_id
        statement_line.matched_at = datetime.now(timezone.utc)
        statement_line.matched_by_id = uuid.UUID(actor_id) if _is_uuid(actor_id) else None
        await self.session.flush()

        logger.info(
            "bank_statement_line_matched",
            statement_line_id=str(statement_line_id),
            payment_type=payment_type,
            payment_id=str(payment_id),
        )
        return statement_line


def _payment_date(payment, payment_type: str) -> date:
    return payment.executed_date if payment_type == "outgoing" else payment.received_date


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
