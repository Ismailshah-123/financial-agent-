"""
app.api.v1.invoices
======================
HTTP endpoints for AP Invoices.

`approve_invoice` is the one endpoint in this router that touches two
services, not one: `InvoiceService.approve` (status transition) and
`PostingService.post_invoice_approval` (the resulting GL entry — debit
expense, credit accounts payable). They're orchestrated here rather than
inside `InvoiceService` itself, because approval is fundamentally a
cross-cutting business event (status change + ledger effect), and the
router is the natural place for that composition until/unless a
dedicated `ApprovalService` is warranted (worth revisiting once a second
"approve X -> post Y" flow exists and the duplication is real, not
speculative). Both calls happen inside the same request/session, so
either both commit or neither does — no risk of a status change without
its ledger entry.

This endpoint is deliberately separate from
`app.api.v1.agents.run_accounts_payable_agent`: the agent only ever
*recommends*; a human approver calling this endpoint is what actually
authorizes the transaction, per the platform's "AI never transacts
without approval" rule.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Currency, Permission
from app.db.models.enums import InvoiceStatus
from app.db.session import get_db
from app.schemas.invoice import InvoiceCreate, InvoiceRead
from app.services.invoice_service import InvoiceService
from app.services.posting_service import PostingService

router = APIRouter(prefix="/invoices", tags=["invoices"])


class RejectInvoiceRequest(BaseModel):
    reason: str


@router.post("", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
async def ingest_invoice(
    payload: InvoiceCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.INVOICE_CREATE)),
) -> InvoiceRead:
    service = InvoiceService(session)
    invoice = await service.ingest_invoice(payload, actor_id=actor.user_id)
    await session.commit()
    return InvoiceRead.model_validate(invoice)


@router.get("/{invoice_id}", response_model=InvoiceRead)
async def get_invoice(
    invoice_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.INVOICE_READ)),
) -> InvoiceRead:
    service = InvoiceService(session)
    invoice = await service.get_invoice(invoice_id)
    return InvoiceRead.model_validate(invoice)


@router.get("", response_model=list[InvoiceRead])
async def list_invoices_by_status(
    status_filter: InvoiceStatus,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.INVOICE_READ)),
) -> list[InvoiceRead]:
    service = InvoiceService(session)
    invoices = await service.repository.list_by_status(status_filter)
    return [InvoiceRead.model_validate(inv) for inv in invoices]


@router.post("/{invoice_id}/approve", response_model=InvoiceRead)
async def approve_invoice(
    invoice_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.INVOICE_APPROVE)),
) -> InvoiceRead:
    invoice_service = InvoiceService(session)
    posting_service = PostingService(session)

    invoice = await invoice_service.get_invoice(invoice_id)
    invoice = await invoice_service.approve(invoice, actor_id=actor.user_id)
    await posting_service.post_invoice_approval(
        invoice_id=invoice.id,
        amount=invoice.total_amount,
        currency=Currency(invoice.currency),
        posting_date=date.today(),
        actor_id=actor.user_id,
    )
    await session.commit()
    return InvoiceRead.model_validate(invoice)


@router.post("/{invoice_id}/reject", response_model=InvoiceRead)
async def reject_invoice(
    invoice_id: uuid.UUID,
    payload: RejectInvoiceRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.INVOICE_APPROVE)),
) -> InvoiceRead:
    service = InvoiceService(session)
    invoice = await service.get_invoice(invoice_id)
    invoice = await service.reject(invoice, actor_id=actor.user_id, reason=payload.reason)
    await session.commit()
    return InvoiceRead.model_validate(invoice)
