"""
app.services.incoming_payment_service
========================================
Use-case layer for recording customer payments. `record_payment` is the
single entrypoint: validates the amount against what's actually
outstanding on the invoice, creates the `IncomingPayment` row (status
`EXECUTED` immediately — see `app.db.models.incoming_payment`'s
docstring on why), posts the journal entry (debit cash, credit
receivable) via `PostingService`, and updates the invoice's running
`amount_paid` total — and therefore its status — via
`ARInvoiceService.apply_balance_change`, the single shared place that
logic lives (see that method's docstring for why `CreditMemoService`
uses the same one).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Currency
from app.core.exceptions import ValidationError
from app.core.logging import get_audit_logger, get_logger
from app.db.models.incoming_payment import IncomingPayment
from app.repositories.ar_invoice_repository import ARInvoiceRepository
from app.repositories.incoming_payment_repository import IncomingPaymentRepository
from app.schemas.incoming_payment import IncomingPaymentCreate
from app.services.ar_invoice_service import ARInvoiceService
from app.services.numbering import generate_document_number
from app.services.posting_service import PostingService

logger = get_logger(__name__)


class IncomingPaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = IncomingPaymentRepository(session)
        self.ar_invoice_repository = ARInvoiceRepository(session)
        self.ar_invoice_service = ARInvoiceService(session)
        self.posting_service = PostingService(session)

    async def record_payment(
        self, payload: IncomingPaymentCreate, *, actor_id: str
    ) -> IncomingPayment:
        invoice = await self.ar_invoice_repository.get_by_id_or_raise(payload.ar_invoice_id)

        if payload.amount > invoice.amount_outstanding:
            raise ValidationError(
                f"Payment amount ({payload.amount}) exceeds the invoice's "
                f"outstanding balance ({invoice.amount_outstanding}).",
                details={"ar_invoice_id": str(invoice.id)},
            )

        payment = IncomingPayment(
            payment_number=generate_document_number("RCPT"),
            customer_id=invoice.customer_id,
            ar_invoice_id=invoice.id,
            amount=payload.amount,
            currency=invoice.currency,
            payment_method=payload.payment_method,
            received_date=payload.received_date,
            bank_reference=payload.bank_reference,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        payment = await self.repository.add(payment)

        await self.posting_service.post_incoming_payment_received(
            incoming_payment_id=payment.id,
            amount=payment.amount,
            currency=Currency(payment.currency),
            posting_date=payload.received_date,
            actor_id=actor_id,
        )
        await self.ar_invoice_service.apply_balance_change(invoice, paid_delta=payment.amount)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="incoming_payment.record",
            resource_type="incoming_payment",
            resource_id=str(payment.id),
            outcome="success",
            metadata={"ar_invoice_id": str(invoice.id), "amount": str(payment.amount)},
        )
        logger.info(
            "incoming_payment_recorded", payment_id=str(payment.id), ar_invoice_id=str(invoice.id)
        )
        return payment


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
