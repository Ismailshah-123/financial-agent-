"""
app.services.payment_service
===============================
Use-case layer for Outgoing Payments. Scheduling a payment
(`schedule_payment`) requires the invoice to already be `APPROVED` —
enforced here, not trusted from the caller — and `execute_payment` is
the single most guarded operation in the platform: it posts the
corresponding journal entry (via `PostingService`) and marks the
payment `EXECUTED`, which the AP agent's `rollback_strategy` treats as
irreversible (see `app.db.models.payment` docstring).

This is deliberately NOT wired to a real bank/payment rail in this
phase — `execute_payment` simulates settlement (marks executed,
generates a bank reference) so the full approval-to-ledger flow is
provable end-to-end before a real payment rail integration (a Treasury
Agent concern, Phase 2) is added.

WITHHOLDING TAX
------------------
`schedule_payment` accepts an optional `withholding_tax_code`. When
supplied, `TaxCalculationService.calculate_withholding_tax` computes
the amount to withhold from the invoice total (see that service's
docstring for the filer/non-filer rate distinction and why this isn't
applied automatically to every payment), and:
    - `OutgoingPayment.amount` stores the NET amount actually
      transferred to the vendor (invoice total minus withholding).
    - `withholding_tax_amount`/`withholding_tax_code` record what was
      withheld and under which tax code, for audit and for FBR
      remittance reporting later.
    - `PostingService.post_payment_execution` receives the FULL invoice
      amount (not the net) so the vendor's AP liability is cleared
      completely, while only the net cash actually leaves — the
      withheld portion becomes a liability owed to the tax authority
      instead (see that method's docstring).
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Currency
from app.core.exceptions import ValidationError
from app.core.logging import get_audit_logger, get_logger
from app.db.models.enums import InvoiceStatus, PaymentStatus
from app.db.models.payment import OutgoingPayment
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import PaymentCreate
from app.services.numbering import generate_document_number
from app.services.posting_service import PostingService
from app.services.tax_service import TaxCalculationService

logger = get_logger(__name__)


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = PaymentRepository(session)
        self.invoice_repository = InvoiceRepository(session)
        self.posting_service = PostingService(session)
        self.tax_service = TaxCalculationService(session)

    async def schedule_payment(
        self, payload: PaymentCreate, *, actor_id: str
    ) -> OutgoingPayment:
        invoice = await self.invoice_repository.get_by_id_or_raise(payload.invoice_id)
        if invoice.status != InvoiceStatus.APPROVED.value:
            raise ValidationError(
                f"Invoice {invoice.id} must be APPROVED before a payment can be "
                f"scheduled (current status: {invoice.status}).",
                details={"invoice_id": str(invoice.id), "status": invoice.status},
            )

        existing = await self.repository.get_by_invoice_id(invoice.id)
        if existing is not None:
            raise ValidationError(
                f"A payment already exists for invoice {invoice.id}.",
                details={"existing_payment_id": str(existing.id)},
            )

        net_amount = invoice.total_amount
        withholding_tax_amount = None
        withholding_tax_code = None
        if payload.withholding_tax_code:
            wht_result = await self.tax_service.calculate_withholding_tax(
                gross_amount=invoice.total_amount,
                tax_code=payload.withholding_tax_code,
                as_of=payload.scheduled_date,
            )
            withholding_tax_amount = wht_result.tax_amount
            withholding_tax_code = wht_result.tax_code
            net_amount = invoice.total_amount - withholding_tax_amount

        payment = OutgoingPayment(
            payment_number=generate_document_number("PMT"),
            vendor_id=invoice.vendor_id,
            invoice_id=invoice.id,
            status=PaymentStatus.SCHEDULED.value,
            amount=net_amount,
            currency=invoice.currency,
            payment_method=payload.payment_method,
            scheduled_date=payload.scheduled_date,
            withholding_tax_code=withholding_tax_code,
            withholding_tax_amount=withholding_tax_amount or 0,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        payment = await self.repository.add(payment)
        await self.invoice_repository.update(
            invoice, status=InvoiceStatus.SCHEDULED_FOR_PAYMENT.value
        )

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="payment.schedule",
            resource_type="payment",
            resource_id=str(payment.id),
            outcome="success",
            metadata={
                "invoice_id": str(invoice.id),
                "net_amount": str(payment.amount),
                "withholding_tax_amount": str(payment.withholding_tax_amount),
            },
        )
        logger.info(
            "payment_scheduled",
            payment_id=str(payment.id),
            invoice_id=str(invoice.id),
            withheld=str(payment.withholding_tax_amount),
        )
        return payment

    async def execute_payment(
        self, payment_id: uuid.UUID, *, actor_id: str
    ) -> OutgoingPayment:
        payment = await self.repository.get_by_id_for_update(payment_id)
        if payment is None:
            raise ValidationError(f"Payment {payment_id} not found.")
        if payment.status == PaymentStatus.EXECUTED.value:
            return payment
        if payment.status not in (PaymentStatus.SCHEDULED.value, PaymentStatus.APPROVED.value):
            raise ValidationError(
                f"Payment {payment.id} cannot be executed from status "
                f"'{payment.status}'.",
            )

        # PostingService.post_payment_execution expects the FULL AP
        # liability being cleared, not the net cash transferred — see
        # its own docstring on why.
        full_amount = payment.amount + payment.withholding_tax_amount

        try:
            await self.posting_service.post_payment_execution(
                payment_id=payment.id,
                amount=full_amount,
                currency=Currency(payment.currency),
                posting_date=date.today(),
                actor_id=actor_id,
                withholding_tax_amount=payment.withholding_tax_amount,
            )
        except Exception as exc:
            payment = await self.repository.update(
                payment,
                status=PaymentStatus.FAILED.value,
                failure_reason=str(exc),
            )
            await get_audit_logger().record(session=self.session, 
                actor_id=actor_id,
                action="payment.execute",
                resource_type="payment",
                resource_id=str(payment.id),
                outcome="failed",
                metadata={"reason": str(exc)},
            )
            raise

        payment = await self.repository.update(
            payment,
            status=PaymentStatus.EXECUTED.value,
            executed_date=date.today(),
            bank_reference=f"SIM-{uuid.uuid4().hex[:12].upper()}",
        )

        invoice = await self.invoice_repository.get_by_id_or_raise(payment.invoice_id)
        await self.invoice_repository.update(invoice, status=InvoiceStatus.PAID.value)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="payment.execute",
            resource_type="payment",
            resource_id=str(payment.id),
            outcome="success",
            metadata={"bank_reference": payment.bank_reference},
        )
        logger.info("payment_executed", payment_id=str(payment.id))
        return payment


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
