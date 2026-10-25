"""
app.repositories.invoice_repository
======================================
Invoice data access. Beyond generic CRUD, this is where the query
patterns the Accounts Payable agent and reporting need live:
duplicate-invoice detection (same vendor + invoice number — a classic
AP fraud/error signal the agent checks before matching), status-scoped
listing (e.g. "all invoices in MATCH_FAILED for human review"), and
overdue lookups for the Collections/Treasury side later.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import and_
from sqlalchemy.orm import selectinload

from app.db.models.enums import InvoiceStatus
from app.db.models.invoice import Invoice
from app.repositories.base_repository import BaseRepository


class InvoiceRepository(BaseRepository[Invoice]):
    model = Invoice

    async def get_by_id_with_lines(self, id_: uuid.UUID) -> Invoice | None:
        stmt = (
            self._base_select()
            .where(Invoice.id == id_)
            .options(selectinload(Invoice.lines))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    async def get_by_id_with_lines_for_update(self, id_: uuid.UUID) -> Invoice | None:
        stmt = (
            self._base_select()
            .where(Invoice.id == id_)
            .with_for_update().options(selectinload(Invoice.lines))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_potential_duplicate(
        self, *, vendor_id: uuid.UUID, invoice_number: str
    ) -> Invoice | None:
        """Same vendor + same invoice number already on file — the
        AP agent treats a hit here as a high-risk signal even before
        running the 3-way match."""
        stmt = self._base_select().where(
            and_(Invoice.vendor_id == vendor_id, Invoice.invoice_number == invoice_number)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_status(
        self, status: InvoiceStatus, *, offset: int = 0, limit: int = 25
    ) -> list[Invoice]:
        stmt = self._base_select().where(Invoice.status == status).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_payable(self) -> list[Invoice]:
        """Every invoice `APPriorityService` needs to categorize:
        MATCHED (successfully matched, awaiting human approval — see
        app.services.ap_priority_service module docstring for why this
        is MATCHED and not the unused InvoiceStatus.PENDING_APPROVAL
        member), MATCH_FAILED (blocked), APPROVED (ready to schedule),
        and SCHEDULED_FOR_PAYMENT (payment in flight or failed — the exact
        sub-state comes from the linked OutgoingPayment, fetched
        separately by `PaymentRepository.list_by_invoice_ids`, since
        Invoice has no reverse relationship to OutgoingPayment to eager
        load here). Deliberately excludes PAID and VOID — a settled or
        cancelled invoice is not a "payment obligation"; the AP
        priority view's "already executed" section is served from
        `PaymentRepository.list_executed_since` instead, bounded by a
        recency window rather than loading full payment history (see
        that method's own docstring). No pagination here for the same
        reason `ARInvoiceRepository.list_open_for_aging` has none:
        prioritization needs the whole payable set to rank correctly,
        not a page of it — pagination applies afterward, in
        `APPriorityService`, over the already-computed results."""
        stmt = (
            self._base_select()
            .where(
                Invoice.status.in_(
                    [
                        InvoiceStatus.MATCHED.value,
                        InvoiceStatus.MATCH_FAILED.value,
                        InvoiceStatus.APPROVED.value,
                        InvoiceStatus.SCHEDULED_FOR_PAYMENT.value,
                    ]
                )
            )
            .options(selectinload(Invoice.vendor))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_overdue(
        self, *, as_of: date, offset: int = 0, limit: int = 25
    ) -> list[Invoice]:
        stmt = (
            self._base_select()
            .where(
                and_(
                    Invoice.due_date < as_of,
                    Invoice.status.notin_(
                        [InvoiceStatus.PAID.value, InvoiceStatus.VOID.value]
                    ),
                )
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
