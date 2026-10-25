"""
app.services.ar_invoice_service
==================================
Use-case layer for AR Invoices — the mirror of `app.services.invoice_service`.

KEY DIFFERENCE FROM THE AP SIDE: no separate "approve" step
----------------------------------------------------------------
An AP invoice needs human approval before it becomes a payment
obligation, because approving it authorizes money to LEAVE the company —
exactly the risk the platform's core AI-approval rule exists for. An AR
invoice does the opposite: it's the company billing a customer, so
`send_invoice` (DRAFT -> SENT) both recognizes revenue AND posts the
journal entry in one step, without a separate human gate. This is a
deliberate asymmetry, not an inconsistency — see
`PostingService.post_ar_invoice_issuance`'s docstring.

Where AR *does* need the same approval discipline as AP is credit
memos (they reduce revenue/receivables, a real financial reversal) —
that gating lives in `app.services.credit_memo_service`, not here.

`ingest_invoice` accepts an optional `tax_code` (see
`app.schemas.ar_invoice.ARInvoiceCreate`'s docstring) — same pattern as
the AP side's `InvoiceService.ingest_invoice`.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Currency
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_audit_logger, get_logger
from app.db.models.ar_invoice import ARInvoice, ARInvoiceLine
from app.db.models.enums import ARInvoiceStatus
from app.repositories.ar_invoice_repository import ARInvoiceRepository
from app.repositories.customer_repository import CustomerRepository
from app.schemas.ar_invoice import ARInvoiceCreate
from app.services.posting_service import PostingService
from app.services.tax_service import TaxCalculationService

logger = get_logger(__name__)


def compute_ar_invoice_status(
    *,
    total_amount: Decimal,
    amount_paid: Decimal,
    amount_credited: Decimal,
    current_status: ARInvoiceStatus,
) -> ARInvoiceStatus:
    """
    Pure function deciding what status an AR invoice should have after
    its paid/credited totals change. Deliberately free of any DB or
    session dependency so it's directly unit-testable (see
    tests/unit/test_ar_invoice_service.py) — `apply_balance_change`
    below is the only caller that also persists the result.

    VOID is a terminal status this function never overrides — once an
    invoice is voided, payment/credit activity against it is a data
    problem to investigate, not something that should silently move it
    back into the normal lifecycle.
    """
    if current_status == ARInvoiceStatus.VOID:
        return current_status

    outstanding = total_amount - amount_paid - amount_credited
    if outstanding <= 0:
        return ARInvoiceStatus.PAID
    if amount_paid > 0 or amount_credited > 0:
        return ARInvoiceStatus.PARTIALLY_PAID
    return current_status


class ARInvoiceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ARInvoiceRepository(session)
        self.customer_repository = CustomerRepository(session)
        self.posting_service = PostingService(session)
        self.tax_service = TaxCalculationService(session)

    async def ingest_invoice(self, payload: ARInvoiceCreate, *, actor_id: str) -> ARInvoice:
        await self.customer_repository.get_by_id_or_raise(payload.customer_id)

        duplicate = await self.repository.find_potential_duplicate(
            customer_id=payload.customer_id, invoice_number=payload.invoice_number
        )
        if duplicate is not None:
            raise ValidationError(
                f"An AR invoice numbered '{payload.invoice_number}' already exists "
                f"for this customer.",
                details={"existing_invoice_id": str(duplicate.id)},
            )

        lines_total = sum(
            (line.quantity * line.unit_price for line in payload.lines), Decimal("0")
        )
        if abs(lines_total - payload.subtotal) > 1:
            raise ValidationError(
                "AR invoice subtotal does not reconcile with the sum of its lines.",
                details={
                    "declared_subtotal": str(payload.subtotal),
                    "computed_from_lines": str(lines_total),
                },
            )

        tax_amount = payload.tax_amount
        total_amount = payload.total_amount
        if payload.tax_code:
            tax_result = await self.tax_service.calculate_sales_tax(
                subtotal=payload.subtotal, tax_code=payload.tax_code, as_of=payload.invoice_date
            )
            tax_amount = tax_result.tax_amount
            total_amount = payload.subtotal + tax_amount

        invoice = ARInvoice(
            invoice_number=payload.invoice_number,
            customer_id=payload.customer_id,
            status=ARInvoiceStatus.DRAFT.value,
            currency=payload.currency.value,
            subtotal=payload.subtotal,
            tax_amount=tax_amount,
            total_amount=total_amount,
            invoice_date=payload.invoice_date,
            due_date=payload.due_date,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        invoice.lines = [
            ARInvoiceLine(
                line_number=line.line_number,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                line_total=line.quantity * line.unit_price,
            )
            for line in payload.lines
        ]
        invoice = await self.repository.add(invoice)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="ar_invoice.ingest",
            resource_type="ar_invoice",
            resource_id=str(invoice.id),
            outcome="success",
            metadata={
                "invoice_number": invoice.invoice_number,
                "customer_id": str(invoice.customer_id),
                "total_amount": str(invoice.total_amount),
            },
        )
        logger.info(
            "ar_invoice_ingested", invoice_id=str(invoice.id), invoice_number=invoice.invoice_number
        )
        return invoice

    async def send_invoice(self, invoice_id: uuid.UUID, *, actor_id: str) -> ARInvoice:
        """DRAFT -> SENT. Recognizes revenue and posts the journal entry
        in the same step — see module docstring for why this doesn't go
        through a separate approval gate the way AP invoice approval does."""
        invoice = await self.get_invoice(invoice_id)
        if invoice.status != ARInvoiceStatus.DRAFT.value:
            raise ValidationError(
                f"AR invoice {invoice.id} must be in DRAFT to be sent "
                f"(current status: {invoice.status})."
            )

        invoice = await self.repository.update(invoice, status=ARInvoiceStatus.SENT.value)
        await self.posting_service.post_ar_invoice_issuance(
            ar_invoice_id=invoice.id,
            amount=invoice.total_amount,
            currency=Currency(invoice.currency),
            posting_date=date.today(),
            actor_id=actor_id,
        )

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="ar_invoice.send",
            resource_type="ar_invoice",
            resource_id=str(invoice.id),
            outcome="success",
        )
        logger.info("ar_invoice_sent", invoice_id=str(invoice.id))
        return invoice

    async def mark_overdue(self, invoice: ARInvoice, *, actor_id: str) -> ARInvoice:
        """Called by the AR Agent when it finds a SENT/PARTIALLY_PAID
        invoice past its due date — a pure status annotation, no
        financial mutation, so it doesn't need approval gating."""
        if invoice.status not in (ARInvoiceStatus.SENT.value, ARInvoiceStatus.PARTIALLY_PAID.value):
            return invoice
        invoice = await self.repository.update(invoice, status=ARInvoiceStatus.OVERDUE.value)
        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="ar_invoice.mark_overdue",
            resource_type="ar_invoice",
            resource_id=str(invoice.id),
            outcome="success",
        )
        return invoice

    async def get_invoice(self, invoice_id: uuid.UUID) -> ARInvoice:
        invoice = await self.repository.get_by_id_with_lines(invoice_id)
        if invoice is None:
            raise NotFoundError(f"AR invoice {invoice_id} not found.")
        return invoice

    async def apply_balance_change(
        self,
        invoice: ARInvoice,
        *,
        paid_delta: Decimal = Decimal("0"),
        credited_delta: Decimal = Decimal("0"),
    ) -> ARInvoice:
        """The one place `amount_paid`/`amount_credited` are mutated and
        `status` is recomputed from them (via the pure
        `compute_ar_invoice_status`). Called by
        `IncomingPaymentService` (paid_delta only) and
        `CreditMemoService` (credited_delta only) — never mutate these
        columns directly from another service."""
        new_paid = invoice.amount_paid + paid_delta
        new_credited = invoice.amount_credited + credited_delta
        new_status = compute_ar_invoice_status(
            total_amount=invoice.total_amount,
            amount_paid=new_paid,
            amount_credited=new_credited,
            current_status=ARInvoiceStatus(invoice.status),
        )
        return await self.repository.update(
            invoice,
            amount_paid=new_paid,
            amount_credited=new_credited,
            status=new_status.value,
        )


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
