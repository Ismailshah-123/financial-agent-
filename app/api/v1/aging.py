"""
app.api.v1.aging
====================
Read-only HTTP endpoints for the AR aging / collections-priority
report. Every number here comes from `AgingService`, which in turn
comes entirely from `app.services.aging_calculations` — no total,
bucket, or priority tier is computed in this router or in the
frontend that eventually consumes it (see that module's docstring for
the actual math). `POST /api/v1/agents/collections/run` (the agent
invocation endpoint, which persists decisions and can require
approval) lives in `app.api.v1.agents` alongside every other
`{agent}/run` endpoint, not here — this router is deliberately
read-only, matching the product brief's own instruction to keep the
aging report and the collections agent as separate concerns.

All four endpoints require `Permission.AR_INVOICE_READ` — the same
permission `app.api.v1.ar_invoices` already gates invoice-level AR
reads with, reused rather than inventing a new `aging:read`/
`collections:read` permission for what is, underneath, the same AR
data viewed a different way.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.aging import (CustomerAgingRead, InvoiceAgingRead, PortfolioAgingSummaryRead, PortfolioCurrencyBalanceRead)
from app.schemas.common import PaginatedResponse, PaginationParams
from app.services.aging_calculations import AgingBucket, PortfolioAgingSummary, PriorityTier
from app.services.aging_service import AgingService

router = APIRouter(prefix="/aging", tags=["aging"])


def _resolve_as_of(as_of: date | None) -> date:
    return as_of if as_of is not None else date.today()


def _bucket_percentages(summary) -> dict[str, float]:
    total = summary.total_outstanding
    if total is None or total <= 0:
        return {}
    return {
        "current": float(summary.current_amount / total * 100),
        "1-30": float(summary.amount_1_30 / total * 100),
        "31-60": float(summary.amount_31_60 / total * 100),
        "61-90": float(summary.amount_61_90 / total * 100),
        "91-120": float(summary.amount_91_120 / total * 100),
        "121+": float(summary.amount_121_plus / total * 100),
    }


@router.get("/summary", response_model=PortfolioAgingSummaryRead)
async def get_aging_summary(
    as_of: date | None = Query(default=None, description="Defaults to today."),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AR_INVOICE_READ)),
) -> PortfolioAgingSummaryRead:
    service = AgingService(session)
    summary = await service.get_portfolio_summary(as_of=_resolve_as_of(as_of))
    return PortfolioAgingSummaryRead(
        as_of=summary.as_of,
        currency=summary.currency,
        total_outstanding=summary.total_outstanding,
        overdue_amount=summary.overdue_amount,
        current_amount=summary.current_amount,
        amount_1_30=summary.amount_1_30,
        amount_31_60=summary.amount_31_60,
        amount_61_90=summary.amount_61_90,
        amount_91_120=summary.amount_91_120,
        amount_121_plus=summary.amount_121_plus,
        open_invoice_count=summary.open_invoice_count,
        overdue_invoice_count=summary.overdue_invoice_count,
        customer_count=summary.customer_count,
        oldest_days_overdue=summary.oldest_days_overdue,
        currency_balances=[
            PortfolioCurrencyBalanceRead.model_validate(balance).model_copy(
                update={"bucket_percentages": _bucket_percentages(balance)}
            ) for balance in summary.currency_balances
        ],
        bucket_percentages=_bucket_percentages(summary),
    )


@router.get("/invoices", response_model=PaginatedResponse[InvoiceAgingRead])
async def list_aging_invoices(
    as_of: date | None = Query(default=None, description="Defaults to today."),
    customer_id: uuid.UUID | None = Query(default=None),
    bucket: AgingBucket | None = Query(default=None),
    minimum_amount: Decimal | None = Query(default=None, ge=0),
    search: str | None = Query(
        default=None, max_length=100, description="Matches invoice number or customer name."
    ),
    pagination: PaginationParams = Depends(),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AR_INVOICE_READ)),
) -> PaginatedResponse[InvoiceAgingRead]:
    service = AgingService(session)
    records, total = await service.list_invoice_aging(
        as_of=_resolve_as_of(as_of),
        customer_id=customer_id,
        bucket=bucket,
        minimum_amount=minimum_amount,
        search=search,
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    return PaginatedResponse[InvoiceAgingRead](
        items=[InvoiceAgingRead.model_validate(r) for r in records],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/customers", response_model=PaginatedResponse[CustomerAgingRead])
async def list_aging_customers(
    as_of: date | None = Query(default=None, description="Defaults to today."),
    risk: PriorityTier | None = Query(default=None, description="low | medium | high | critical"),
    priority: PriorityTier | None = Query(default=None, description="low | medium | high | critical"),
    minimum_amount: Decimal | None = Query(default=None, ge=0),
    search: str | None = Query(default=None, max_length=100, description="Matches customer name."),
    pagination: PaginationParams = Depends(),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AR_INVOICE_READ)),
) -> PaginatedResponse[CustomerAgingRead]:
    service = AgingService(session)
    summaries, total = await service.list_customer_aging(
        as_of=_resolve_as_of(as_of),
        risk=risk,
        priority=priority,
        minimum_amount=minimum_amount,
        search=search,
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    return PaginatedResponse[CustomerAgingRead](
        items=[CustomerAgingRead.model_validate(s) for s in summaries],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/customer/{customer_id}", response_model=CustomerAgingRead)
async def get_customer_aging_detail(
    customer_id: uuid.UUID,
    as_of: date | None = Query(default=None, description="Defaults to today."),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AR_INVOICE_READ)),
) -> CustomerAgingRead:
    service = AgingService(session)
    summary = await service.get_customer_aging(customer_id, as_of=_resolve_as_of(as_of))
    return CustomerAgingRead.model_validate(summary)
