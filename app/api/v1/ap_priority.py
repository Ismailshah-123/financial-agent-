"""
app.api.v1.ap_priority
==========================
Read-only HTTP endpoints for AP payment prioritization — money owed BY
the company, the counterpart to `app.api.v1.aging` (money owed TO it).
Every number comes from `APPriorityService`, which comes entirely from
`app.services.ap_priority_calculations` — no status categorization,
due-date bucket, or priority score is computed in this router. There is
no agent and no `/run` endpoint for this feature: the product brief
(§4) scopes this as a read layer only, unlike Collections — nothing
here is meant to call an LLM or create an approval-inbox decision.

No payment is ever executed by any endpoint in this router. Scheduling
and executing payments stay exactly where they already were, in
`app.api.v1.payments` via `PaymentService` — this file only reports on
what's owed and how urgent it is.

All four endpoints require `Permission.INVOICE_READ`, the same
permission `app.api.v1.invoices` already gates AP invoice reads with.
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
from app.schemas.ap_priority import APPrioritySummaryRead, PaymentObligationRead, VendorExposureRead
from app.schemas.common import PaginatedResponse, PaginationParams
from app.services.ap_priority_calculations import PaymentPriorityStatus, PriorityTier
from app.services.ap_priority_service import APPriorityService

router = APIRouter(prefix="/ap-priority", tags=["ap-priority"])


def _resolve_as_of(as_of: date | None) -> date:
    return as_of if as_of is not None else date.today()


@router.get("/summary", response_model=APPrioritySummaryRead)
async def get_ap_priority_summary(
    as_of: date | None = Query(default=None, description="Defaults to today."),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.INVOICE_READ)),
) -> APPrioritySummaryRead:
    service = APPriorityService(session)
    summary = await service.get_summary(as_of=_resolve_as_of(as_of))
    return APPrioritySummaryRead(**summary)


@router.get("/obligations", response_model=PaginatedResponse[PaymentObligationRead])
async def list_payment_obligations(
    as_of: date | None = Query(default=None, description="Defaults to today."),
    vendor_id: uuid.UUID | None = Query(default=None),
    status: PaymentPriorityStatus | None = Query(default=None),
    priority: PriorityTier | None = Query(default=None, description="low | medium | high | critical"),
    minimum_amount: Decimal | None = Query(default=None, ge=0),
    search: str | None = Query(
        default=None, max_length=100, description="Matches invoice number or vendor name."
    ),
    include_executed: bool = Query(
        default=False,
        description="Include payments executed in the last 30 days (see APPriorityService).",
    ),
    pagination: PaginationParams = Depends(),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.INVOICE_READ)),
) -> PaginatedResponse[PaymentObligationRead]:
    service = APPriorityService(session)
    obligations, total = await service.list_obligations(
        as_of=_resolve_as_of(as_of),
        vendor_id=vendor_id,
        status=status,
        priority=priority,
        minimum_amount=minimum_amount,
        search=search,
        include_executed=include_executed,
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    return PaginatedResponse[PaymentObligationRead](
        items=[PaymentObligationRead.model_validate(o) for o in obligations],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/vendors", response_model=PaginatedResponse[VendorExposureRead])
async def list_vendor_exposure(
    as_of: date | None = Query(default=None, description="Defaults to today."),
    search: str | None = Query(default=None, max_length=100, description="Matches vendor name."),
    pagination: PaginationParams = Depends(),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.INVOICE_READ)),
) -> PaginatedResponse[VendorExposureRead]:
    service = APPriorityService(session)
    summaries, total = await service.list_vendor_exposure(
        as_of=_resolve_as_of(as_of), search=search, offset=pagination.offset, limit=pagination.page_size
    )
    return PaginatedResponse[VendorExposureRead](
        items=[VendorExposureRead.model_validate(s) for s in summaries],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/vendor/{vendor_id}", response_model=VendorExposureRead)
async def get_vendor_exposure_detail(
    vendor_id: uuid.UUID,
    as_of: date | None = Query(default=None, description="Defaults to today."),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.INVOICE_READ)),
) -> VendorExposureRead:
    service = APPriorityService(session)
    summary = await service.get_vendor_exposure(vendor_id, as_of=_resolve_as_of(as_of))
    return VendorExposureRead.model_validate(summary)
