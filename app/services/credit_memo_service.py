"""
app.services.credit_memo_service
===================================
Use-case layer for both `ARCreditMemo` and `APCreditMemo` issuance.
Unlike routine AR invoice issuance (`ARInvoiceService.send_invoice`,
which posts immediately with no approval gate — see its docstring),
credit memos on EITHER side are financial reversals with real leakage
risk (a fraudulent or mistaken credit memo directly reduces revenue
owed to the company, or improperly reduces what the company appears to
owe a vendor) and so are created in DRAFT status here but are NOT
auto-applied to the related invoice's balance — application happens via
the separate `apply_ar_credit_memo` / `apply_ap_credit_memo` methods,
intended to be called only after human approval, mirroring the AP
invoice approve-then-post pattern.

AR credit memo application updates `ARInvoice.amount_credited` via
`ARInvoiceService.apply_balance_change` (never sets it directly) — that
column is dedicated to credit-memo adjustments and kept separate from
`amount_paid` (cash only, moved exclusively by
`IncomingPaymentService`), so AR reporting can distinguish "collected in
cash" from "written off via credit" as two different questions instead
of one conflated running total.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Currency
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_audit_logger, get_logger
from app.db.models.credit_memo import (
    APCreditMemo,
    APCreditMemoLine,
    ARCreditMemo,
    ARCreditMemoLine,
)
from app.db.models.enums import CreditMemoStatus
from app.repositories.ar_invoice_repository import ARInvoiceRepository
from app.repositories.credit_memo_repository import APCreditMemoRepository, ARCreditMemoRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.vendor_repository import VendorRepository
from app.schemas.credit_memo import APCreditMemoCreate, ARCreditMemoCreate
from app.services.ar_invoice_service import ARInvoiceService
from app.services.posting_service import PostingService

logger = get_logger(__name__)


class CreditMemoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ar_repository = ARCreditMemoRepository(session)
        self.ap_repository = APCreditMemoRepository(session)
        self.customer_repository = CustomerRepository(session)
        self.vendor_repository = VendorRepository(session)
        self.ar_invoice_repository = ARInvoiceRepository(session)
        self.invoice_repository = InvoiceRepository(session)
        self.posting_service = PostingService(session)
        self.ar_invoice_service = ARInvoiceService(session)

    # ------------------------------------------------------------------
    # AR side — a credit WE issue to a customer
    # ------------------------------------------------------------------
    async def issue_ar_credit_memo(
        self, payload: ARCreditMemoCreate, *, actor_id: str
    ) -> ARCreditMemo:
        await self.customer_repository.get_by_id_or_raise(payload.customer_id)

        if payload.related_ar_invoice_id is not None:
            related_invoice = await self.ar_invoice_repository.get_by_id_or_raise(
                payload.related_ar_invoice_id
            )
            if related_invoice.customer_id != payload.customer_id:
                raise ValidationError(
                    "The related AR invoice does not belong to this customer."
                )
            if payload.total_amount > related_invoice.amount_outstanding:
                raise ConflictError(
                    f"Credit memo amount ({payload.total_amount}) exceeds the "
                    f"related invoice's outstanding balance "
                    f"({related_invoice.amount_outstanding}).",
                    details={"ar_invoice_id": str(related_invoice.id)},
                )

        memo = ARCreditMemo(
            credit_memo_number=payload.credit_memo_number,
            customer_id=payload.customer_id,
            related_ar_invoice_id=payload.related_ar_invoice_id,
            status=CreditMemoStatus.DRAFT.value,
            currency=payload.currency.value,
            subtotal=payload.subtotal,
            tax_amount=payload.tax_amount,
            total_amount=payload.total_amount,
            memo_date=payload.memo_date,
            reason=payload.reason,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        memo.lines = [
            ARCreditMemoLine(
                line_number=line.line_number,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                line_total=line.quantity * line.unit_price,
            )
            for line in payload.lines
        ]
        memo = await self.ar_repository.add(memo)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="ar_credit_memo.issue",
            resource_type="ar_credit_memo",
            resource_id=str(memo.id),
            outcome="success",
            metadata={"customer_id": str(memo.customer_id), "amount": str(memo.total_amount)},
        )
        logger.info("ar_credit_memo_issued", credit_memo_id=str(memo.id))
        return memo

    async def apply_ar_credit_memo(
        self, credit_memo_id: uuid.UUID, *, actor_id: str
    ) -> ARCreditMemo:
        """Human-approved application: posts the journal entry and, if
        tied to a specific invoice, reduces that invoice's outstanding
        balance (see module docstring's noted limitation on how that's
        tracked). Not called automatically by `issue_ar_credit_memo` —
        the caller (API layer) invokes this only after approval,
        mirroring `InvoiceService.approve` + `PostingService.
        post_invoice_approval` on the AP side."""
        # get_by_id_with_lines (not get_by_id_or_raise): the caller
        # returns this object through ARCreditMemoRead, which
        # serializes `.lines` — an un-eager-loaded relationship
        # accessed outside the session's async context raises
        # MissingGreenlet at serialization time, not here, which
        # makes it look like a response-model bug rather than the
        # missing eager load it actually is.
        memo = await self.ar_repository.get_by_id_with_lines(credit_memo_id)
        if memo is None:
            raise NotFoundError(
                f"ARCreditMemo with id {credit_memo_id} not found.",
                details={"model": "ARCreditMemo", "id": str(credit_memo_id)},
            )
        if memo.status != CreditMemoStatus.DRAFT.value:
            raise ValidationError(
                f"Credit memo {memo.id} must be DRAFT to be applied "
                f"(current status: {memo.status})."
            )

        await self.posting_service.post_ar_credit_memo(
            credit_memo_id=memo.id,
            amount=memo.total_amount,
            currency=Currency(memo.currency),
            posting_date=date.today(),
            actor_id=actor_id,
        )

        if memo.related_ar_invoice_id is not None:
            related_invoice = await self.ar_invoice_repository.get_by_id_or_raise(
                memo.related_ar_invoice_id
            )
            await self.ar_invoice_service.apply_balance_change(
                related_invoice, credited_delta=memo.total_amount
            )

        memo = await self.ar_repository.update(memo, status=CreditMemoStatus.APPLIED.value)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="ar_credit_memo.apply",
            resource_type="ar_credit_memo",
            resource_id=str(memo.id),
            outcome="success",
        )
        logger.info("ar_credit_memo_applied", credit_memo_id=str(memo.id))
        return memo

    # ------------------------------------------------------------------
    # AP side — a credit a VENDOR issues to us
    # ------------------------------------------------------------------
    async def issue_ap_credit_memo(
        self, payload: APCreditMemoCreate, *, actor_id: str
    ) -> APCreditMemo:
        await self.vendor_repository.get_by_id_or_raise(payload.vendor_id)

        if payload.related_invoice_id is not None:
            related_invoice = await self.invoice_repository.get_by_id_or_raise(
                payload.related_invoice_id
            )
            if related_invoice.vendor_id != payload.vendor_id:
                raise ValidationError(
                    "The related invoice does not belong to this vendor."
                )

        memo = APCreditMemo(
            credit_memo_number=payload.credit_memo_number,
            vendor_id=payload.vendor_id,
            related_invoice_id=payload.related_invoice_id,
            status=CreditMemoStatus.DRAFT.value,
            currency=payload.currency.value,
            subtotal=payload.subtotal,
            tax_amount=payload.tax_amount,
            total_amount=payload.total_amount,
            memo_date=payload.memo_date,
            reason=payload.reason,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        memo.lines = [
            APCreditMemoLine(
                line_number=line.line_number,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                line_total=line.quantity * line.unit_price,
            )
            for line in payload.lines
        ]
        memo = await self.ap_repository.add(memo)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="ap_credit_memo.issue",
            resource_type="ap_credit_memo",
            resource_id=str(memo.id),
            outcome="success",
            metadata={"vendor_id": str(memo.vendor_id), "amount": str(memo.total_amount)},
        )
        logger.info("ap_credit_memo_issued", credit_memo_id=str(memo.id))
        return memo

    async def apply_ap_credit_memo(
        self, credit_memo_id: uuid.UUID, *, actor_id: str
    ) -> APCreditMemo:
        # See apply_ar_credit_memo's comment above — same reason.
        memo = await self.ap_repository.get_by_id_with_lines(credit_memo_id)
        if memo is None:
            raise NotFoundError(
                f"APCreditMemo with id {credit_memo_id} not found.",
                details={"model": "APCreditMemo", "id": str(credit_memo_id)},
            )
        if memo.status != CreditMemoStatus.DRAFT.value:
            raise ValidationError(
                f"Credit memo {memo.id} must be DRAFT to be applied "
                f"(current status: {memo.status})."
            )

        await self.posting_service.post_ap_credit_memo(
            credit_memo_id=memo.id,
            amount=memo.total_amount,
            currency=Currency(memo.currency),
            posting_date=date.today(),
            actor_id=actor_id,
        )
        memo = await self.ap_repository.update(memo, status=CreditMemoStatus.APPLIED.value)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="ap_credit_memo.apply",
            resource_type="ap_credit_memo",
            resource_id=str(memo.id),
            outcome="success",
        )
        logger.info("ap_credit_memo_applied", credit_memo_id=str(memo.id))
        return memo


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
