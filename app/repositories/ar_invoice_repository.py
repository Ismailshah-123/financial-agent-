"""
app.repositories.ar_invoice_repository
=========================================
AR Invoice data access — the mirror of `InvoiceRepository`. Adds the
query patterns the AR Agent and collections workflow need: duplicate
detection (same customer + invoice number), status-scoped listing, and
overdue lookups (the core input to any collections/dunning logic).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import and_
from sqlalchemy.orm import selectinload

from app.db.models.ar_invoice import ARInvoice
from app.db.models.enums import ARInvoiceStatus
from app.repositories.base_repository import BaseRepository


class ARInvoiceRepository(BaseRepository[ARInvoice]):
    model = ARInvoice

    async def get_by_id_with_lines(self, id_: uuid.UUID) -> ARInvoice | None:
        stmt = (
            self._base_select()
            .where(ARInvoice.id == id_)
            .options(selectinload(ARInvoice.lines))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    async def get_by_id_with_lines_for_update(self, id_: uuid.UUID) -> ARInvoice | None:
        stmt = (
            self._base_select()
            .where(ARInvoice.id == id_)
            .with_for_update().options(selectinload(ARInvoice.lines))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_potential_duplicate(
        self, *, customer_id: uuid.UUID, invoice_number: str
    ) -> ARInvoice | None:
        stmt = self._base_select().where(
            and_(
                ARInvoice.customer_id == customer_id,
                ARInvoice.invoice_number == invoice_number,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_status(
        self, status: ARInvoiceStatus, *, offset: int = 0, limit: int = 25
    ) -> list[ARInvoice]:
        stmt = (
            self._base_select().where(ARInvoice.status == status).offset(offset).limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_overdue(
        self, *, as_of: date, offset: int = 0, limit: int = 25
    ) -> list[ARInvoice]:
        stmt = (
            self._base_select()
            .where(
                and_(
                    ARInvoice.due_date < as_of,
                    ARInvoice.status.notin_(
                        [ARInvoiceStatus.PAID.value, ARInvoiceStatus.VOID.value]
                    ),
                )
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_due_within_range(
        self, *, start_date: date, end_date: date
    ) -> list[ARInvoice]:
        """Open (not PAID/VOID) invoices due within [start_date,
        end_date] — the receivables side of
        TreasuryService.forecast_cash_flow's inflow projection.
        `ARInvoice.amount_outstanding` (not total_amount) is what the
        caller sums, so a PARTIALLY_PAID invoice only contributes its
        remaining balance."""
        stmt = self._base_select().where(
            and_(
                ARInvoice.due_date >= start_date,
                ARInvoice.due_date <= end_date,
                ARInvoice.status.notin_(
                    [ARInvoiceStatus.PAID.value, ARInvoiceStatus.VOID.value]
                ),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_customer(
        self, customer_id: uuid.UUID, *, offset: int = 0, limit: int = 25
    ) -> list[ARInvoice]:
        stmt = (
            self._base_select()
            .where(ARInvoice.customer_id == customer_id)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_open_for_aging(
        self, *, customer_id: uuid.UUID | None = None
    ) -> list[ARInvoice]:
        """Every invoice that belongs on an aging report: excludes both
        DRAFT and VOID. This is a deliberate divergence from
        `list_overdue`/`list_due_within_range` above, which exclude
        only PAID/VOID (so they still include DRAFT) — correct for
        those callers (Treasury needs every committed future
        receivable), wrong here: a draft invoice was never sent to the
        customer, so it isn't part of what they actually owe yet, and
        showing it on an aging report would misrepresent real customer
        exposure. PAID invoices ARE included here (unlike
        `list_overdue`) because `AgingService`/`aging_calculations`
        need to see them to correctly report zero outstanding for a
        settled invoice, not just silently drop it — the "open"
        filtering (amount_outstanding > 0) happens in
        `aging_calculations.summarize_customer_aging`/
        `summarize_portfolio_aging`, not here, so this method stays a
        plain, reusable "everything relevant" query.

        No pagination here deliberately: aging math (bucket totals,
        oldest-overdue, priority scoring) needs the customer's/
        portfolio's full invoice set to be correct, not a page of it —
        pagination for the API layer's list views is applied by
        `AgingService` afterwards, over the already-computed records,
        same as `sum_outstanding_for_customer` above already reasons
        about "fine at this data volume, revisit with a SQL aggregate
        if a single customer's open-invoice count ever grows large
        enough for this to matter."
        """
        stmt = (
            self._base_select()
            .where(
                ARInvoice.status.notin_(
                    [ARInvoiceStatus.DRAFT.value, ARInvoiceStatus.VOID.value]
                )
            )
            # Every aging/collections caller needs customer_name — eager
            # load it here rather than letting each row lazy-load its
            # own Customer (an N+1 query per invoice on a real portfolio).
            .options(selectinload(ARInvoice.customer))
        )
        if customer_id is not None:
            stmt = stmt.where(ARInvoice.customer_id == customer_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def sum_outstanding_for_customer(self, customer_id: uuid.UUID) -> Decimal:
        """Total unpaid AR balance for a customer — what the AR Agent
        checks against `Customer.credit_limit`. Computed in Python over
        already-fetched rows rather than a SQL SUM(), since
        `amount_outstanding` is a Python property (total - paid), not a
        stored column; fine at this data volume, revisit with a SQL
        aggregate if a single customer's open-invoice count ever grows
        large enough for this to matter."""
        invoices = await self.list_by_status(ARInvoiceStatus.SENT, limit=1000)
        partially_paid = await self.list_by_status(ARInvoiceStatus.PARTIALLY_PAID, limit=1000)
        overdue = await self.list_by_status(ARInvoiceStatus.OVERDUE, limit=1000)
        relevant = [
            inv
            for inv in (invoices + partially_paid + overdue)
            if inv.customer_id == customer_id
        ]
        return sum((inv.amount_outstanding for inv in relevant), Decimal("0"))
