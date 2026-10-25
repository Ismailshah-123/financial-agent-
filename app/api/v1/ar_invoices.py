"""
app.api.v1.ar_invoices
=========================
HTTP endpoints for AR Invoices. `send_ar_invoice` is the AR equivalent
of the AP side's `/invoices/{id}/approve` in terms of "this is the step
that posts to the ledger" — but note it does NOT require an elevated
approval permission the way AP approval requires `INVOICE_APPROVE`; any
role with `AR_INVOICE_CREATE` can send an invoice it created, since
billing a customer doesn't carry the same risk as authorizing an
outgoing payment. See `ARInvoiceService.send_invoice`'s docstring for
the full reasoning behind this asymmetry.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.models.enums import ARInvoiceStatus
from app.db.session import get_db
from app.schemas.ar_invoice import ARInvoiceCreate, ARInvoiceRead
from app.services.ar_invoice_service import ARInvoiceService

router = APIRouter(prefix="/ar-invoices", tags=["ar-invoices"])


@router.post("", response_model=ARInvoiceRead, status_code=status.HTTP_201_CREATED)
async def ingest_ar_invoice(
    payload: ARInvoiceCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AR_INVOICE_CREATE)),
) -> ARInvoiceRead:
    service = ARInvoiceService(session)
    invoice = await service.ingest_invoice(payload, actor_id=actor.user_id)
    await session.commit()
    return ARInvoiceRead.model_validate(invoice)


@router.get("/{invoice_id}", response_model=ARInvoiceRead)
async def get_ar_invoice(
    invoice_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AR_INVOICE_READ)),
) -> ARInvoiceRead:
    service = ARInvoiceService(session)
    invoice = await service.get_invoice(invoice_id)
    return ARInvoiceRead.model_validate(invoice)


@router.get("", response_model=list[ARInvoiceRead])
async def list_ar_invoices_by_status(
    status_filter: ARInvoiceStatus,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AR_INVOICE_READ)),
) -> list[ARInvoiceRead]:
    service = ARInvoiceService(session)
    invoices = await service.repository.list_by_status(status_filter)
    return [ARInvoiceRead.model_validate(inv) for inv in invoices]


@router.post("/{invoice_id}/send", response_model=ARInvoiceRead)
async def send_ar_invoice(
    invoice_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AR_INVOICE_CREATE)),
) -> ARInvoiceRead:
    service = ARInvoiceService(session)
    invoice = await service.send_invoice(invoice_id, actor_id=actor.user_id)
    await session.commit()
    return ARInvoiceRead.model_validate(invoice)
