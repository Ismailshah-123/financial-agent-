"""
app.services.ap_priority_service
====================================
The async, database-facing half of the AP payment-priority feature —
same split, and the same reasons, as `app.services.aging_service`
relative to `aging_calculations`. This file fetches `Invoice`/
`OutgoingPayment`/`Vendor` rows and feeds their fields into the pure
functions in `app.services.ap_priority_calculations`; it contains no
scoring or categorization logic of its own.

DERIVING PaymentPriorityStatus FROM TWO TABLES' STATUS COLUMNS
--------------------------------------------------------------------
`Invoice.status` alone doesn't carry enough information once an
invoice reaches SCHEDULED_FOR_PAYMENT — see
`app.services.payment_service`: that one invoice status covers a
payment that's cleanly scheduled, one stuck in its own approval step,
one that failed, and (per `PaymentStatus`) one that was cancelled after
scheduling. `_resolve_status` below is the one place that two-table
lookup happens; everything downstream works with the single resolved
`PaymentPriorityStatus` enum from `ap_priority_calculations`.

CANCELLED payments are treated the same as FAILED ones for priority
purposes (not a separate category) — both leave the invoice stuck in
SCHEDULED_FOR_PAYMENT with no code path in this codebase that resets it
back to APPROVED or allows a second payment row (the unique constraint
on `OutgoingPayment.invoice_id` forbids it), so both are the same
"someone needs to step in" problem from this feature's point of view.
See `ap_priority_calculations`' module docstring for the full story on
why PAYMENT_FAILED exists as its own category at all.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.models.enums import InvoiceStatus, PaymentStatus
from app.db.models.invoice import Invoice
from app.db.models.payment import OutgoingPayment
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.vendor_repository import VendorRepository
from app.services.ap_priority_calculations import (
    DueBucket,
    PaymentObligation,
    PaymentPriorityStatus,
    PriorityTier,
    VendorExposureSummary,
    compute_payment_obligation,
    obligation_sort_key,
    summarize_ap_priority,
    summarize_vendor_exposure,
    vendor_sort_key,
)

logger = get_logger(__name__)

DEFAULT_EXECUTED_LOOKBACK_DAYS = 30


def _resolve_status(
    invoice: Invoice, payment: OutgoingPayment | None
) -> tuple[PaymentPriorityStatus, str | None]:
    """Returns (status, status_detail). The one place Invoice.status
    and OutgoingPayment.status are combined into a single priority
    status — see module docstring."""
    if invoice.status == InvoiceStatus.MATCHED.value:
        # Not InvoiceStatus.PENDING_APPROVAL — that enum member exists
        # but is never actually assigned anywhere in this codebase (grep
        # confirms it; app.api.v1.invoices.approve_invoice has no status
        # precondition at all and is called directly on MATCHED
        # invoices in the real flow — see tests/integration/test_ap_flow
        # .py's happy path). MATCHED is the real "awaiting approval"
        # state. Found while building this feature, not assumed.
        return PaymentPriorityStatus.AWAITING_APPROVAL, None
    if invoice.status == InvoiceStatus.MATCH_FAILED.value:
        detail = f"{invoice.match_type} match" if invoice.match_type else None
        return PaymentPriorityStatus.BLOCKED, detail
    if invoice.status == InvoiceStatus.APPROVED.value:
        return PaymentPriorityStatus.READY_TO_SCHEDULE, None
    if invoice.status == InvoiceStatus.SCHEDULED_FOR_PAYMENT.value:
        if payment is None:
            # Shouldn't happen — payment_service.schedule_payment sets
            # both together — but fail safely rather than crash the
            # whole priority list over one inconsistent row.
            logger.warning(
                "ap_priority_missing_payment_for_scheduled_invoice",
                invoice_id=str(invoice.id),
            )
            return PaymentPriorityStatus.READY_TO_SCHEDULE, "data inconsistency: no payment record found"
        if payment.status == PaymentStatus.PENDING_APPROVAL.value:
            return PaymentPriorityStatus.AWAITING_APPROVAL, "payment pending its own approval"
        if payment.status in (
            PaymentStatus.SCHEDULED.value,
            PaymentStatus.APPROVED.value,
            PaymentStatus.EXECUTING.value,
        ):
            return PaymentPriorityStatus.SCHEDULED, None
        if payment.status in (PaymentStatus.FAILED.value, PaymentStatus.CANCELLED.value):
            detail = payment.failure_reason if payment.status == PaymentStatus.FAILED.value else "payment cancelled"
            return PaymentPriorityStatus.PAYMENT_FAILED, detail
        # payment.status == EXECUTED with invoice still SCHEDULED_FOR_PAYMENT
        # would itself be the same kind of inconsistency as the None case.
        logger.warning(
            "ap_priority_unexpected_payment_status_for_scheduled_invoice",
            invoice_id=str(invoice.id),
            payment_status=payment.status,
        )
        return PaymentPriorityStatus.SCHEDULED, None
    # PENDING_APPROVAL/MATCH_FAILED/APPROVED/SCHEDULED_FOR_PAYMENT are the
    # only statuses InvoiceRepository.list_payable returns.
    raise AssertionError(f"unexpected invoice status in payable set: {invoice.status}")


def _invoice_to_obligation(
    invoice: Invoice, payment: OutgoingPayment | None, *, as_of: date
) -> PaymentObligation:
    status, detail = _resolve_status(invoice, payment)
    return compute_payment_obligation(
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        vendor_id=invoice.vendor_id,
        vendor_name=invoice.vendor.name if invoice.vendor is not None else "Unknown vendor",
        amount=invoice.total_amount,
        currency=invoice.currency,
        due_date=invoice.due_date,
        as_of=as_of,
        status=status,
        status_detail=detail,
        scheduled_date=payment.scheduled_date if payment is not None else None,
    )


def _executed_payment_to_obligation(payment: OutgoingPayment, *, as_of: date) -> PaymentObligation:
    invoice = payment.invoice
    return compute_payment_obligation(
        invoice_id=payment.invoice_id,
        invoice_number=invoice.invoice_number if invoice is not None else "Unknown invoice",
        vendor_id=payment.vendor_id,
        vendor_name=payment.vendor.name if payment.vendor is not None else "Unknown vendor",
        amount=payment.amount,
        currency=payment.currency,
        due_date=invoice.due_date if invoice is not None else payment.scheduled_date,
        as_of=as_of,
        status=PaymentPriorityStatus.EXECUTED,
        scheduled_date=payment.scheduled_date,
        executed_date=payment.executed_date,
    )


class APPriorityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.invoice_repository = InvoiceRepository(session)
        self.payment_repository = PaymentRepository(session)
        self.vendor_repository = VendorRepository(session)

    async def _build_obligations(
        self, *, as_of: date, executed_since: date | None
    ) -> list[PaymentObligation]:
        """Every obligation in scope, unfiltered, unpaginated — the one
        place invoice and payment rows are assembled into
        `PaymentObligation`s, shared by every public method below so
        the different views can't disagree about what's in scope."""
        invoices = await self.invoice_repository.list_payable()
        scheduled_ids = [
            inv.id for inv in invoices if inv.status == InvoiceStatus.SCHEDULED_FOR_PAYMENT.value
        ]
        payments = await self.payment_repository.list_by_invoice_ids(scheduled_ids)
        payment_by_invoice_id = {p.invoice_id: p for p in payments}

        obligations = [
            _invoice_to_obligation(inv, payment_by_invoice_id.get(inv.id), as_of=as_of)
            for inv in invoices
        ]

        if executed_since is not None:
            executed_payments = await self.payment_repository.list_executed_since(since=executed_since)
            obligations += [
                _executed_payment_to_obligation(p, as_of=as_of) for p in executed_payments
            ]
        return obligations

    # ------------------------------------------------------------------
    # GET /api/v1/ap-priority/summary
    # ------------------------------------------------------------------
    async def get_summary(self, *, as_of: date) -> dict:
        obligations = await self._build_obligations(
            as_of=as_of, executed_since=as_of - timedelta(days=DEFAULT_EXECUTED_LOOKBACK_DAYS)
        )
        return summarize_ap_priority(as_of=as_of, obligations=obligations)

    # ------------------------------------------------------------------
    # GET /api/v1/ap-priority/obligations
    # ------------------------------------------------------------------
    async def list_obligations(
        self,
        *,
        as_of: date,
        vendor_id: uuid.UUID | None = None,
        status: PaymentPriorityStatus | None = None,
        priority: PriorityTier | None = None,
        minimum_amount: Decimal | None = None,
        search: str | None = None,
        include_executed: bool = False,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[PaymentObligation], int]:
        executed_since = (
            as_of - timedelta(days=DEFAULT_EXECUTED_LOOKBACK_DAYS) if include_executed else None
        )
        obligations = await self._build_obligations(as_of=as_of, executed_since=executed_since)

        if vendor_id is not None:
            obligations = [o for o in obligations if o.vendor_id == vendor_id]
        if status is not None:
            obligations = [o for o in obligations if o.status == status]
        if priority is not None:
            obligations = [o for o in obligations if o.priority == priority]
        if minimum_amount is not None:
            obligations = [o for o in obligations if o.amount >= minimum_amount]
        if search:
            needle = search.strip().lower()
            obligations = [
                o
                for o in obligations
                if needle in o.invoice_number.lower() or needle in o.vendor_name.lower()
            ]

        obligations.sort(key=obligation_sort_key)
        total = len(obligations)
        return obligations[offset : offset + limit], total

    # ------------------------------------------------------------------
    # GET /api/v1/ap-priority/vendors
    # ------------------------------------------------------------------
    async def list_vendor_exposure(
        self,
        *,
        as_of: date,
        search: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[VendorExposureSummary], int]:
        obligations = await self._build_obligations(as_of=as_of, executed_since=None)
        by_vendor: dict[uuid.UUID, list[PaymentObligation]] = {}
        for o in obligations:
            by_vendor.setdefault(o.vendor_id, []).append(o)

        summaries = [
            summarize_vendor_exposure(
                vendor_id=vendor_id,
                vendor_name=items[0].vendor_name,
                currency=items[0].currency,
                obligations=items,
            )
            for vendor_id, items in by_vendor.items()
        ]
        summaries = [
            summary
            for summary in summaries
            if (
                summary.total_exposure is not None and summary.total_exposure > 0
            )
            or any(balance.total_exposure > 0 for balance in summary.currency_balances)
        ]

        if search:
            needle = search.strip().lower()
            summaries = [s for s in summaries if needle in s.vendor_name.lower()]

        summaries.sort(key=vendor_sort_key)
        total = len(summaries)
        return summaries[offset : offset + limit], total

    # ------------------------------------------------------------------
    # GET /api/v1/ap-priority/vendor/{vendor_id}
    # ------------------------------------------------------------------
    async def get_vendor_exposure(
        self, vendor_id: uuid.UUID, *, as_of: date
    ) -> VendorExposureSummary:
        vendor = await self.vendor_repository.get_by_id(vendor_id)
        if vendor is None:
            raise NotFoundError(
                f"Vendor {vendor_id} not found.", details={"vendor_id": str(vendor_id)}
            )
        obligations = await self._build_obligations(as_of=as_of, executed_since=None)
        vendor_obligations = [o for o in obligations if o.vendor_id == vendor_id]
        return summarize_vendor_exposure(
            vendor_id=vendor_id,
            vendor_name=vendor.name,
            currency=vendor.default_currency,
            obligations=vendor_obligations,
        )
