"""
app.api.v1.fbr_remittances
==============================
Endpoints for recording payments made to FBR against withholding tax
liability. See `app.services.fbr_compliance_service` for how these are
compared against liability incurred, and
`app.api.v1.agents.run_compliance_agent` for the AI risk assessment
this API supports but doesn't itself perform.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.fbr_remittance import FBRRemittanceCreate, FBRRemittanceRead
from app.services.fbr_compliance_service import FBRComplianceService

router = APIRouter(prefix="/fbr-remittances", tags=["fbr-remittances"])


@router.post("", response_model=FBRRemittanceRead, status_code=201)
async def record_remittance(
    payload: FBRRemittanceCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.FBR_REMITTANCE_RECORD)),
) -> FBRRemittanceRead:
    service = FBRComplianceService(session)
    remittance = await service.record_remittance(
        period_start=payload.period_start,
        period_end=payload.period_end,
        amount_remitted=payload.amount_remitted,
        currency=payload.currency,
        remitted_date=payload.remitted_date,
        fbr_reference=payload.fbr_reference,
        notes=payload.notes,
        actor_id=actor.user_id,
    )
    await session.commit()
    return FBRRemittanceRead.model_validate(remittance)
