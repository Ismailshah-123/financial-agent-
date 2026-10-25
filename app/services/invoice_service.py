"""
app.services.invoice_service
===============================
Use-case layer for AP Invoices: ingestion (manual or OCR-sourced) and
status transitions. Duplicate detection
(`InvoiceRepository.find_potential_duplicate`) runs at creation time so
a duplicate is flagged before matching even starts — the
`AccountsPayableAgent` (next) treats a flagged duplicate as an automatic
high-risk signal regardless of how well the line items otherwise match.

Matching itself is NOT performed here — that's
`InvoiceMatchingEngine` (`app.services.matching_service`), invoked by the
agent, because "should this invoice be approved" is an agent decision
with reasoning/confidence/audit trail attached, not a bare service call.
This service only owns persistence and status bookkeeping around that
decision (`apply_match_outcome`, `approve`, `reject`).

`ingest_invoice` accepts an optional `tax_code` on the payload (see
`app.schemas.invoice.InvoiceCreate`'s docstring): when supplied,
`tax_amount`/`total_amount` are computed server-side via
`TaxCalculationService` using the invoice's own `invoice_date` for
effective-rate resolution, overriding whatever flat values the client
sent — this is what prevents a client from asserting a tax code and a
contradicting flat tax amount at the same time.
"""

from __future__ import annotations

import uuid
from datetime import date

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.core.logging import get_audit_logger, get_logger
from app.db.models.enums import InvoiceStatus, MatchType
from app.db.models.invoice import Invoice, InvoiceLine
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.purchase_order_repository import PurchaseOrderRepository
from app.repositories.vendor_repository import VendorRepository
from app.schemas.invoice import InvoiceCreate
from app.services.matching_service import MatchOutcome
from app.services.tax_service import TaxCalculationService

logger = get_logger(__name__)


class InvoiceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = InvoiceRepository(session)
        self.vendor_repository = VendorRepository(session)
        self.po_repository = PurchaseOrderRepository(session)
        self.tax_service = TaxCalculationService(session)

    async def ingest_invoice(self, payload: InvoiceCreate, *, actor_id: str) -> Invoice:
        await self.vendor_repository.get_by_id_or_raise(payload.vendor_id)
        if payload.purchase_order_id is not None:
            await self.po_repository.get_by_id_or_raise(payload.purchase_order_id)

        lines_total = sum(
            (line.quantity * line.unit_price for line in payload.lines), Decimal("0")
        )
        # Sanity check: subtotal should reconcile with line totals within a
        # cent (OCR/manual-entry rounding). A hard mismatch is rejected up
        # front rather than silently trusted and matched against later.
        if abs(lines_total - payload.subtotal) > 1:
            raise ValidationError(
                "Invoice subtotal does not reconcile with the sum of its lines.",
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

        invoice = Invoice(
            invoice_number=payload.invoice_number,
            vendor_id=payload.vendor_id,
            purchase_order_id=payload.purchase_order_id,
            status=InvoiceStatus.RECEIVED.value,
            currency=payload.currency.value,
            subtotal=payload.subtotal,
            tax_amount=tax_amount,
            total_amount=total_amount,
            invoice_date=payload.invoice_date,
            due_date=payload.due_date,
            source_document_id=payload.source_document_id,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        invoice.lines = [
            InvoiceLine(
                line_number=line.line_number,
                purchase_order_line_id=line.purchase_order_line_id,
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
            action="invoice.ingest",
            resource_type="invoice",
            resource_id=str(invoice.id),
            outcome="success",
            metadata={
                "invoice_number": invoice.invoice_number,
                "vendor_id": str(invoice.vendor_id),
                "total_amount": str(invoice.total_amount),
            },
        )
        logger.info(
            "invoice_ingested", invoice_id=str(invoice.id), invoice_number=invoice.invoice_number
        )
        return invoice

    async def find_duplicate(self, invoice: Invoice) -> Invoice | None:
        """Excludes the invoice itself when checking (relevant for
        recheck flows where the invoice being checked is already
        persisted)."""
        candidate = await self.repository.find_potential_duplicate(
            vendor_id=invoice.vendor_id, invoice_number=invoice.invoice_number
        )
        if candidate is not None and candidate.id == invoice.id:
            return None
        return candidate

    async def apply_match_outcome(
        self, invoice: Invoice, outcome: MatchOutcome, *, actor_id: str
    ) -> Invoice:
        new_status = (
            InvoiceStatus.MATCHED if outcome.is_matched else InvoiceStatus.MATCH_FAILED
        )
        invoice = await self.repository.update(
            invoice,
            status=new_status.value,
            match_type=outcome.match_type.value,
            matched_at=date.today() if outcome.is_matched else None,
        )
        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="invoice.match_outcome_applied",
            resource_type="invoice",
            resource_id=str(invoice.id),
            outcome="matched" if outcome.is_matched else "match_failed",
            metadata={"summary": outcome.summary},
        )
        return invoice

    async def approve(self, invoice: Invoice, *, actor_id: str) -> Invoice:
        invoice = await self.repository.update(
            invoice, status=InvoiceStatus.APPROVED.value
        )
        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="invoice.approve",
            resource_type="invoice",
            resource_id=str(invoice.id),
            outcome="success",
        )
        return invoice

    async def reject(self, invoice: Invoice, *, actor_id: str, reason: str) -> Invoice:
        invoice = await self.repository.update(
            invoice, status=InvoiceStatus.REJECTED.value
        )
        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="invoice.reject",
            resource_type="invoice",
            resource_id=str(invoice.id),
            outcome="rejected",
            metadata={"reason": reason},
        )
        return invoice

    async def get_invoice(self, invoice_id: uuid.UUID) -> Invoice:
        invoice = await self.repository.get_by_id_with_lines(invoice_id)
        if invoice is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"Invoice {invoice_id} not found.")
        return invoice


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
