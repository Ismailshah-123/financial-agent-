"""
app.api.v1.bank_reconciliation
==================================
Endpoints for ingesting bank statement lines and confirming matches.
See `app.services.bank_reconciliation_service` for the matching logic
and `app.api.v1.agents.run_bank_reconciliation_agent` for the AI
recommendation step this API supports but doesn't itself perform.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.bank_reconciliation import (
    BankStatementLineRead,
    ConfirmMatchRequest,
    IngestStatementLinesRequest,
)
from app.services.bank_reconciliation_service import BankReconciliationService, StatementLineInput

router = APIRouter(prefix="/bank-reconciliation", tags=["bank-reconciliation"])


@router.post("/statement-lines", response_model=list[BankStatementLineRead], status_code=201)
async def ingest_statement_lines(
    payload: IngestStatementLinesRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.BANK_STATEMENT_INGEST)),
) -> list[BankStatementLineRead]:
    service = BankReconciliationService(session)
    lines = await service.ingest_statement_lines(
        statement_label=payload.statement_label,
        lines=[
            StatementLineInput(
                transaction_date=line.transaction_date,
                description=line.description,
                amount=line.amount,
                currency=line.currency,
                bank_reference=line.bank_reference,
            )
            for line in payload.lines
        ],
        actor_id=actor.user_id,
    )
    await session.commit()
    return [BankStatementLineRead.model_validate(line) for line in lines]


@router.get("/statement-lines/{statement_line_id}", response_model=BankStatementLineRead)
async def get_statement_line(
    statement_line_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.BANK_STATEMENT_READ)),
) -> BankStatementLineRead:
    service = BankReconciliationService(session)
    line = await service.repository.get_by_id_or_raise(statement_line_id)
    return BankStatementLineRead.model_validate(line)


@router.post("/statement-lines/{statement_line_id}/confirm-match", response_model=BankStatementLineRead)
async def confirm_match(
    statement_line_id: uuid.UUID,
    payload: ConfirmMatchRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.BANK_STATEMENT_MATCH)),
) -> BankStatementLineRead:
    service = BankReconciliationService(session)
    line = await service.confirm_match(
        statement_line_id=statement_line_id,
        payment_type=payload.payment_type,
        payment_id=payload.payment_id,
        actor_id=actor.user_id,
    )
    await session.commit()
    return BankStatementLineRead.model_validate(line)
