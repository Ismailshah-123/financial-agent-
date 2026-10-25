"""
app.services.posting_service
===============================
The only place in the codebase allowed to create a `JournalEntry`. Every
other module that needs a ledger posting (invoice approval, payment
execution) calls `PostingService.post()` rather than constructing a
`JournalEntry` directly — this is what makes the "no unbalanced journal
entry ever reaches the database" invariant enforceable in one place
instead of trusted-by-convention everywhere.

ACCOUNT CODES
-------------
Hardcoded default account codes below (`ACCOUNTS_PAYABLE`, `CASH`,
`GENERAL_EXPENSE`) are placeholders for a single-entity, single-chart-
of-accounts deployment. A real multi-tenant/multi-entity platform needs
a `ChartOfAccounts` lookup keyed by tenant + GL account purpose — noted
here rather than silently baked in, so this is the file to revisit when
that model exists (Phase 2, alongside multi-tenant hardening).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Currency, TransactionType
from app.core.exceptions import ValidationError
from app.core.logging import get_audit_logger, get_logger
from app.db.models.enums import JournalEntryStatus
from app.db.models.journal_entry import JournalEntry, JournalEntryLine
from app.repositories.journal_entry_repository import JournalEntryRepository
from app.repositories.period_close_repository import PeriodCloseRepository
from app.services.numbering import generate_document_number

logger = get_logger(__name__)


class DefaultAccounts:
    ACCOUNTS_PAYABLE = "2000-AP"
    CASH = "1000-CASH"
    GENERAL_EXPENSE = "5000-EXP"
    ACCOUNTS_RECEIVABLE = "1100-AR"
    REVENUE = "4000-REV"
    PURCHASE_RETURNS = "5100-PURRET"  # contra-expense: reduces net AP expense
    WITHHOLDING_TAX_PAYABLE = "2100-WHT"  # liability: owed to the tax authority
    RETAINED_EARNINGS = "3000-RE"  # equity: what PeriodCloseService closes net income into


@dataclass
class PostingLine:
    account_code: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    description: str | None = None


class PostingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = JournalEntryRepository(session)
        self.period_close_repository = PeriodCloseRepository(session)

    async def post(
        self,
        *,
        transaction_type: TransactionType,
        reference_id: uuid.UUID,
        posting_date: date,
        currency: Currency,
        lines: list[PostingLine],
        actor_id: str,
    ) -> JournalEntry:
        total_debit = sum((line.debit for line in lines), Decimal("0"))
        total_credit = sum((line.credit for line in lines), Decimal("0"))

        if total_debit != total_credit:
            raise ValidationError(
                "Journal entry is unbalanced: debits must equal credits.",
                details={
                    "total_debit": str(total_debit),
                    "total_credit": str(total_credit),
                    "transaction_type": transaction_type.value,
                    "reference_id": str(reference_id),
                },
            )
        if total_debit == 0:
            raise ValidationError("Journal entry cannot have zero total amount.")

        # Period lock: reject any posting dated inside an already-closed,
        # not-reopened period. This is the ONLY enforcement point for that
        # rule — see app.services.period_close_service's module docstring
        # and alembic/versions/0007_period_close.py for why it lives here
        # rather than a DB constraint. Deliberately checked AFTER the pure
        # balance/zero-amount checks above (which stay DB-free — see
        # tests/unit/test_posting_service.py) rather than before: fail fast
        # on the cheap check, and a malformed entry is worth rejecting on
        # its own terms even before asking whether the date is postable.
        # TransactionType.PERIOD_CLOSE itself is exempt: PeriodCloseService.
        # close_period dates its own closing entry at end_date, BEFORE that
        # period's PeriodClose row exists — there's nothing to conflict
        # with yet — and reopen_period's reversing entry is deliberately
        # dated today (a currently-open date), so it never needs this
        # exemption in practice either.
        if transaction_type != TransactionType.PERIOD_CLOSE:
            overlapping = await self.period_close_repository.list_overlapping(
                start_date=posting_date, end_date=posting_date
            )
            if overlapping:
                closed = overlapping[0]
                raise ValidationError(
                    f"Cannot post to {posting_date}: it falls within the closed "
                    f"period {closed.start_date} to {closed.end_date}. Reopen "
                    f"that period first if this posting is genuinely needed.",
                    details={
                        "posting_date": posting_date.isoformat(),
                        "closed_period_start": closed.start_date.isoformat(),
                        "closed_period_end": closed.end_date.isoformat(),
                        "period_close_id": str(closed.id),
                    },
                )

        entry = JournalEntry(
            entry_number=generate_document_number("JE"),
            transaction_type=transaction_type.value,
            reference_id=reference_id,
            status=JournalEntryStatus.POSTED.value,
            posting_date=posting_date,
            currency=currency.value,
            total_debit=total_debit,
            total_credit=total_credit,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        entry.lines = [
            JournalEntryLine(
                line_number=idx + 1,
                account_code=line.account_code,
                description=line.description,
                debit=line.debit,
                credit=line.credit,
            )
            for idx, line in enumerate(lines)
        ]
        entry = await self.repository.add(entry)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="journal_entry.post",
            resource_type="journal_entry",
            resource_id=str(entry.id),
            outcome="success",
            metadata={
                "transaction_type": transaction_type.value,
                "reference_id": str(reference_id),
                "total_debit": str(total_debit),
            },
        )
        logger.info(
            "journal_entry_posted",
            entry_id=str(entry.id),
            entry_number=entry.entry_number,
            transaction_type=transaction_type.value,
        )
        return entry

    async def post_invoice_approval(
        self,
        *,
        invoice_id: uuid.UUID,
        amount: Decimal,
        currency: Currency,
        posting_date,
        actor_id: str,
        expense_account: str = DefaultAccounts.GENERAL_EXPENSE,
    ) -> JournalEntry:
        """Debit expense, credit accounts payable — the standard entry
        when an AP invoice is approved (liability recognized, not yet paid)."""
        return await self.post(
            transaction_type=TransactionType.AP_INVOICE,
            reference_id=invoice_id,
            posting_date=posting_date,
            currency=currency,
            lines=[
                PostingLine(
                    account_code=expense_account,
                    debit=amount,
                    description="Invoice approved — expense recognized",
                ),
                PostingLine(
                    account_code=DefaultAccounts.ACCOUNTS_PAYABLE,
                    credit=amount,
                    description="Invoice approved — AP liability recognized",
                ),
            ],
            actor_id=actor_id,
        )

    async def post_payment_execution(
        self,
        *,
        payment_id: uuid.UUID,
        amount: Decimal,
        currency: Currency,
        posting_date,
        actor_id: str,
        withholding_tax_amount: Decimal = Decimal("0"),
    ) -> JournalEntry:
        """Debit accounts payable (the FULL invoice liability being
        cleared), credit cash (only the NET amount actually
        transferred), and — when `withholding_tax_amount` is nonzero —
        credit withholding tax payable for the difference. This is what
        correctly clears the vendor's full AP balance while moving less
        cash than the invoice total: the withheld portion becomes a
        liability owed to the tax authority instead of to the vendor,
        it doesn't just vanish from the books.

        `amount` here is the FULL invoice/AP amount being cleared
        (`amount = net_cash_transferred + withholding_tax_amount`), not
        just the net transfer — callers pass the invoice total, not
        `OutgoingPayment.amount` (which stores the net). See
        `PaymentService.execute_payment` for how these are threaded
        through correctly.
        """
        cash_amount = amount - withholding_tax_amount
        lines = [
            PostingLine(
                account_code=DefaultAccounts.ACCOUNTS_PAYABLE,
                debit=amount,
                description="Payment executed — AP liability cleared",
            ),
            PostingLine(
                account_code=DefaultAccounts.CASH,
                credit=cash_amount,
                description="Payment executed — cash outflow",
            ),
        ]
        if withholding_tax_amount > 0:
            lines.append(
                PostingLine(
                    account_code=DefaultAccounts.WITHHOLDING_TAX_PAYABLE,
                    credit=withholding_tax_amount,
                    description="Payment executed — withholding tax payable to tax authority",
                )
            )
        return await self.post(
            transaction_type=TransactionType.OUTGOING_PAYMENT,
            reference_id=payment_id,
            posting_date=posting_date,
            currency=currency,
            lines=lines,
            actor_id=actor_id,
        )

    async def post_ar_invoice_issuance(
        self,
        *,
        ar_invoice_id: uuid.UUID,
        amount: Decimal,
        currency: Currency,
        posting_date,
        actor_id: str,
        revenue_account: str = DefaultAccounts.REVENUE,
    ) -> JournalEntry:
        """Debit accounts receivable, credit revenue — the standard
        entry when an AR invoice is sent to a customer (revenue
        recognized, receivable created). Mirrors `post_invoice_approval`
        on the AP side, but AR revenue recognition is tied to the
        invoice being SENT rather than a separate approval step, since
        billing a customer doesn't carry the same "AI might authorize an
        unwanted payment" risk that gates AP approval."""
        return await self.post(
            transaction_type=TransactionType.AR_INVOICE,
            reference_id=ar_invoice_id,
            posting_date=posting_date,
            currency=currency,
            lines=[
                PostingLine(
                    account_code=DefaultAccounts.ACCOUNTS_RECEIVABLE,
                    debit=amount,
                    description="AR invoice sent — receivable recognized",
                ),
                PostingLine(
                    account_code=revenue_account,
                    credit=amount,
                    description="AR invoice sent — revenue recognized",
                ),
            ],
            actor_id=actor_id,
        )

    async def post_ar_credit_memo(
        self,
        *,
        credit_memo_id: uuid.UUID,
        amount: Decimal,
        currency: Currency,
        posting_date,
        actor_id: str,
        revenue_account: str = DefaultAccounts.REVENUE,
    ) -> JournalEntry:
        """Debit revenue (reduces recognized revenue), credit accounts
        receivable (reduces what the customer owes) — the standard
        entry when we issue a credit memo to a customer."""
        return await self.post(
            transaction_type=TransactionType.CREDIT_NOTE,
            reference_id=credit_memo_id,
            posting_date=posting_date,
            currency=currency,
            lines=[
                PostingLine(
                    account_code=revenue_account,
                    debit=amount,
                    description="AR credit memo issued — revenue reduced",
                ),
                PostingLine(
                    account_code=DefaultAccounts.ACCOUNTS_RECEIVABLE,
                    credit=amount,
                    description="AR credit memo issued — receivable reduced",
                ),
            ],
            actor_id=actor_id,
        )

    async def post_ap_credit_memo(
        self,
        *,
        credit_memo_id: uuid.UUID,
        amount: Decimal,
        currency: Currency,
        posting_date,
        actor_id: str,
        purchase_returns_account: str = DefaultAccounts.PURCHASE_RETURNS,
    ) -> JournalEntry:
        """Debit accounts payable (reduces what we owe the vendor),
        credit purchase returns (a contra-expense account) — the
        standard entry when a vendor issues us a credit memo."""
        return await self.post(
            transaction_type=TransactionType.DEBIT_NOTE,
            reference_id=credit_memo_id,
            posting_date=posting_date,
            currency=currency,
            lines=[
                PostingLine(
                    account_code=DefaultAccounts.ACCOUNTS_PAYABLE,
                    debit=amount,
                    description="AP credit memo received — liability reduced",
                ),
                PostingLine(
                    account_code=purchase_returns_account,
                    credit=amount,
                    description="AP credit memo received — purchase returns recognized",
                ),
            ],
            actor_id=actor_id,
        )

    async def post_incoming_payment_received(
        self,
        *,
        incoming_payment_id: uuid.UUID,
        amount: Decimal,
        currency: Currency,
        posting_date,
        actor_id: str,
    ) -> JournalEntry:
        """Debit cash, credit accounts receivable — the standard entry
        when a customer payment is recorded as received."""
        return await self.post(
            transaction_type=TransactionType.INCOMING_PAYMENT,
            reference_id=incoming_payment_id,
            posting_date=posting_date,
            currency=currency,
            lines=[
                PostingLine(
                    account_code=DefaultAccounts.CASH,
                    debit=amount,
                    description="Incoming payment received — cash inflow",
                ),
                PostingLine(
                    account_code=DefaultAccounts.ACCOUNTS_RECEIVABLE,
                    credit=amount,
                    description="Incoming payment received — receivable cleared",
                ),
            ],
            actor_id=actor_id,
        )


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
