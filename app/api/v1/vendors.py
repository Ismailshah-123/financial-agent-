"""
app.api.v1.vendors
=====================
HTTP endpoints for Vendor management. Thin by design — every handler
does auth (`Depends(require_permission(...))`), delegates to
`VendorService`, commits the session, and returns a `*Read` schema.
Business rules (duplicate tax id rejection, PENDING_REVIEW default
status) live in the service, not here — see `app.services.vendor_service`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.core.security import role_has_permission
from app.db.session import get_db
from app.schemas.common import PaginatedResponse, PaginationParams
from app.schemas.vendor import VendorCreate, VendorRead, VendorRiskAssessmentRequest, VendorUpdate
from app.services.vendor_service import VendorService

router = APIRouter(prefix="/vendors", tags=["vendors"])


def _vendor_response(vendor: object, actor: ActorContext) -> VendorRead:
    """Serialize vendor data while protecting bank coordinates by permission.

    Bank details are never included simply because a user has general vendor
    read, invoice read, or vendor creation permissions.
    """
    result = VendorRead.model_validate(vendor)
    if not role_has_permission(actor.role, Permission.VENDOR_BANK_DETAILS_READ):
        result = result.model_copy(update={"bank_account_iban": None, "bank_account_swift": None})
    return result


@router.post("", response_model=VendorRead, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    payload: VendorCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.VENDOR_CREATE)),
) -> VendorRead:
    service = VendorService(session)
    vendor = await service.create_vendor(payload, actor_id=actor.user_id)
    await session.commit()
    return _vendor_response(vendor, actor)


@router.get("/{vendor_id}", response_model=VendorRead)
async def get_vendor(
    vendor_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.VENDOR_READ)),
) -> VendorRead:
    service = VendorService(session)
    vendor = await service.get_vendor(vendor_id)
    return _vendor_response(vendor, actor)


@router.get("", response_model=PaginatedResponse[VendorRead])
async def list_vendors(
    pagination: PaginationParams = Depends(),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.VENDOR_READ)),
) -> PaginatedResponse[VendorRead]:
    service = VendorService(session)
    vendors = await service.repository.list_all(
        offset=pagination.offset, limit=pagination.page_size
    )
    total = await service.repository.count_all()
    return PaginatedResponse[VendorRead](
        items=[_vendor_response(v, actor) for v in vendors],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.patch("/{vendor_id}", response_model=VendorRead)
async def update_vendor(
    vendor_id: uuid.UUID,
    payload: VendorUpdate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.VENDOR_MANAGE)),
) -> VendorRead:
    service = VendorService(session)
    vendor = await service.update_vendor(vendor_id, payload, actor_id=actor.user_id)
    await session.commit()
    return _vendor_response(vendor, actor)


@router.post("/{vendor_id}/activate", response_model=VendorRead)
async def activate_vendor(
    vendor_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.VENDOR_MANAGE)),
) -> VendorRead:
    service = VendorService(session)
    vendor = await service.activate_vendor(vendor_id, actor_id=actor.user_id)
    await session.commit()
    return _vendor_response(vendor, actor)


@router.post("/{vendor_id}/risk-assessment", response_model=VendorRead)
async def apply_vendor_risk_assessment(
    vendor_id: uuid.UUID,
    payload: VendorRiskAssessmentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.VENDOR_MANAGE)),
) -> VendorRead:
    service = VendorService(session)
    vendor = await service.apply_risk_assessment(
        vendor_id,
        risk_rating=payload.risk_rating,
        new_status=payload.new_status,
        reason=payload.reason,
        actor_id=actor.user_id,
    )
    await session.commit()
    return _vendor_response(vendor, actor)
