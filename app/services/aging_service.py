"""
app.services.aging_service
=============================
The async, database-facing half of the Collections/Aging feature.
`AgingService` fetches `ARInvoice`/`Customer` rows via the existing
repositories and feeds their fields into the pure functions in
`app.services.aging_calculations` — it deliberately contains no
business logic of its own (no bucket math, no scoring), so there is
exactly one place either could be wrong, and that place is importable
and unit-testable without a database (see that module's docstring).

WHY THIS IS A SEPARATE FILE FROM aging_calculations.py, UNLIKE
TREASURY/FRAUD'S "PURE FUNCTIONS ALONGSIDE THE SERVICE CLASS" PATTERN
------------------------------------------------------------------------------
`TreasuryService` and `FraudDetectionService` keep their pure helpers
in the same file as the AsyncSession-using class. Aging/collections
splits them into two files instead, for a real reason beyond style:
this feature's pure layer is large enough (bucket assignment, per
invoice and per-customer aggregation, and a four-signal priority
score) to warrant being reviewed, imported, and tested on its own
without pulling in SQLAlchemy at all — including in environments where
SQLAlchemy isn't installed. Worth stating plainly since it's a
divergence from the pattern the rest of this codebase uses, not an
oversight.

PAGINATION AND FILTERING HAPPEN IN PYTHON, OVER ALREADY-COMPUTED RESULTS
----------------------------------------------------------------------------
Bucket, risk/priority tier, and priority_score are all derived values —
none of them are stored columns, so none of them can be pushed into a
SQL WHERE clause. Every method below fetches the relevant invoice set
once, runs it through `aging_calculations`, then filters/sorts/paginates
the resulting Python list. Same "fine at this data volume, revisit with
a SQL-level aggregate if it ever grows large enough to matter" reasoning
`ARInvoiceRepository.sum_outstanding_for_customer` already documents —
stated here rather than silently repeated.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.ar_invoice import ARInvoice
from app.repositories.ar_invoice_repository import ARInvoiceRepository
from app.repositories.customer_repository import CustomerRepository
from app.services.aging_calculations import (
    AgingBucket,
    CustomerAgingSummary,
    InvoiceAgingRecord,
    PortfolioAgingSummary,
    PriorityTier,
    compute_invoice_aging,
    customer_sort_key,
    invoice_sort_key,
    summarize_customer_aging,
    summarize_portfolio_aging,
)


def _invoice_to_record(invoice: ARInvoice, *, as_of: date) -> InvoiceAgingRecord:
    """The one place an ORM `ARInvoice` row is translated into the pure
    calculation layer's plain-value input — every method below goes
    through this, so a field renamed on the model only needs updating
    here."""
    return compute_invoice_aging(
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        customer_id=invoice.customer_id,
        customer_name=invoice.customer.name if invoice.customer is not None else "Unknown customer",
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        total_amount=invoice.total_amount,
        amount_paid=invoice.amount_paid,
        amount_credited=invoice.amount_credited,
        currency=invoice.currency,
        status=invoice.status,
        as_of=as_of,
    )


class AgingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ar_invoice_repository = ARInvoiceRepository(session)
        self.customer_repository = CustomerRepository(session)

    # ------------------------------------------------------------------
    # GET /api/v1/aging/summary
    # ------------------------------------------------------------------
    async def get_portfolio_summary(self, *, as_of: date) -> PortfolioAgingSummary:
        invoices = await self.ar_invoice_repository.list_open_for_aging()
        records = [_invoice_to_record(inv, as_of=as_of) for inv in invoices]
        return summarize_portfolio_aging(as_of=as_of, invoices=records)

    # ------------------------------------------------------------------
    # GET /api/v1/aging/invoices
    # ------------------------------------------------------------------
    async def list_invoice_aging(
        self,
        *,
        as_of: date,
        customer_id: uuid.UUID | None = None,
        bucket: AgingBucket | None = None,
        minimum_amount: Decimal | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[InvoiceAgingRecord], int]:
        """Returns (page of records, total matching count) — the shape
        `PaginatedResponse` needs. Only invoices with a positive
        outstanding balance are considered "open" for this listing
        (see aging_calculations module docstring); a fully paid or
        fully credited invoice still computed cleanly by
        `compute_invoice_aging` just never appears here."""
        invoices = await self.ar_invoice_repository.list_open_for_aging(customer_id=customer_id)
        records = [_invoice_to_record(inv, as_of=as_of) for inv in invoices]
        records = [r for r in records if r.amount_outstanding > 0]

        if bucket is not None:
            records = [r for r in records if r.bucket == bucket]
        if minimum_amount is not None:
            records = [r for r in records if r.amount_outstanding >= minimum_amount]
        if search:
            needle = search.strip().lower()
            records = [
                r
                for r in records
                if needle in r.invoice_number.lower() or needle in r.customer_name.lower()
            ]

        records.sort(key=invoice_sort_key)
        total = len(records)
        page = records[offset : offset + limit]
        return page, total

    # ------------------------------------------------------------------
    # Shared by list_customer_aging (API) and list_all_customer_aging (agent)
    # ------------------------------------------------------------------
    async def _build_customer_summaries(self, *, as_of: date) -> list[CustomerAgingSummary]:
        """Every customer with a nonzero outstanding balance, unsorted,
        unfiltered, unpaginated. The single place customer summaries are
        assembled from invoice rows, so the API list and the agent's
        portfolio run can never disagree about who is in scope."""
        invoices = await self.ar_invoice_repository.list_open_for_aging()
        records_by_customer: dict[uuid.UUID, list[InvoiceAgingRecord]] = {}
        customer_names: dict[uuid.UUID, str] = {}
        customer_credit_limits: dict[uuid.UUID, Decimal | None] = {}
        customer_currencies: dict[uuid.UUID, str] = {}
        for invoice in invoices:
            record = _invoice_to_record(invoice, as_of=as_of)
            records_by_customer.setdefault(invoice.customer_id, []).append(record)
            customer_names[invoice.customer_id] = record.customer_name
            customer_credit_limits[invoice.customer_id] = (
                invoice.customer.credit_limit if invoice.customer is not None else None
            )
            customer_currencies[invoice.customer_id] = (
                invoice.customer.default_currency
                if invoice.customer is not None
                else invoice.currency
            )

        summaries = [
            summarize_customer_aging(
                customer_id=customer_id,
                customer_name=customer_names[customer_id],
                currency=customer_currencies[customer_id],
                credit_limit=customer_credit_limits[customer_id],
                invoices=customer_invoices,
                as_of=as_of,
            )
            for customer_id, customer_invoices in records_by_customer.items()
        ]
        # A customer whose whole book is settled (total_outstanding == 0)
        # isn't part of an aging report: they owe nothing. Mirrors the
        # invoice-level "> 0" filter in list_invoice_aging.
        return [
            summary
            for summary in summaries
            if (
                summary.total_outstanding is not None and summary.total_outstanding > 0
            )
            or any(balance.total_outstanding > 0 for balance in summary.currency_balances)
        ]

    # ------------------------------------------------------------------
    # GET /api/v1/aging/customers
    # ------------------------------------------------------------------
    async def list_customer_aging(
        self,
        *,
        as_of: date,
        risk: PriorityTier | None = None,
        priority: PriorityTier | None = None,
        minimum_amount: Decimal | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[CustomerAgingSummary], int]:
        summaries = await self._build_customer_summaries(as_of=as_of)

        if risk is not None:
            summaries = [s for s in summaries if s.risk == risk]
        if priority is not None:
            summaries = [s for s in summaries if s.priority == priority]
        if minimum_amount is not None:
            summaries = [
                summary
                for summary in summaries
                if (
                    summary.total_outstanding is not None
                    and summary.total_outstanding >= minimum_amount
                )
                or any(
                    balance.total_outstanding >= minimum_amount
                    for balance in summary.currency_balances
                )
            ]
        if search:
            needle = search.strip().lower()
            summaries = [s for s in summaries if needle in s.customer_name.lower()]

        summaries.sort(key=customer_sort_key)
        total = len(summaries)
        page = summaries[offset : offset + limit]
        return page, total

    # ------------------------------------------------------------------
    # GET /api/v1/aging/customer/{customer_id}
    # ------------------------------------------------------------------
    async def get_customer_aging(
        self, customer_id: uuid.UUID, *, as_of: date
    ) -> CustomerAgingSummary:
        customer = await self.customer_repository.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError(
                f"Customer {customer_id} not found.", details={"customer_id": str(customer_id)}
            )
        invoices = await self.ar_invoice_repository.list_open_for_aging(customer_id=customer_id)
        records = [_invoice_to_record(inv, as_of=as_of) for inv in invoices]
        return summarize_customer_aging(
            customer_id=customer_id,
            customer_name=customer.name,
            currency=customer.default_currency,
            credit_limit=customer.credit_limit,
            invoices=records,
            as_of=as_of,
        )

    # ------------------------------------------------------------------
    # Used by CollectionsAgent for a portfolio-wide run
    # ------------------------------------------------------------------
    async def list_all_customer_aging(self, *, as_of: date) -> list[CustomerAgingSummary]:
        """Every customer with a nonzero outstanding balance, unpaginated
        and unfiltered, worst first (same deterministic order as the
        paginated API list). Built from the same private helper as
        `list_customer_aging` rather than calling it with a huge `limit`,
        so the agent's contract can't silently change if the API
        method's paging behaviour ever does."""
        summaries = await self._build_customer_summaries(as_of=as_of)
        summaries.sort(key=customer_sort_key)
        return summaries
