"""
app.api.v1.customers
=======================
HTTP endpoints for Customer management — the AR mirror of
app.api.v1.vendors. Same thin-router pattern: permission check ->
service call -> commit -> response.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.common import PaginatedResponse, PaginationParams
from app.schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate
from app.services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.CUSTOMER_CREATE)),
) -> CustomerRead:
    service = CustomerService(session)
    customer = await service.create_customer(payload, actor_id=actor.user_id)
    await session.commit()
    return CustomerRead.model_validate(customer)


@router.get("/{customer_id}", response_model=CustomerRead)
async def get_customer(
    customer_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.CUSTOMER_READ)),
) -> CustomerRead:
    service = CustomerService(session)
    customer = await service.get_customer(customer_id)
    return CustomerRead.model_validate(customer)


@router.get("", response_model=PaginatedResponse[CustomerRead])
async def list_customers(
    pagination: PaginationParams = Depends(),
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.CUSTOMER_READ)),
) -> PaginatedResponse[CustomerRead]:
    service = CustomerService(session)
    customers = await service.repository.list_all(
        offset=pagination.offset, limit=pagination.page_size
    )
    total = await service.repository.count_all()
    return PaginatedResponse[CustomerRead](
        items=[CustomerRead.model_validate(c) for c in customers],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.patch("/{customer_id}", response_model=CustomerRead)
async def update_customer(
    customer_id: uuid.UUID,
    payload: CustomerUpdate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.CUSTOMER_MANAGE)),
) -> CustomerRead:
    service = CustomerService(session)
    customer = await service.update_customer(customer_id, payload, actor_id=actor.user_id)
    await session.commit()
    return CustomerRead.model_validate(customer)


@router.post("/{customer_id}/activate", response_model=CustomerRead)
async def activate_customer(
    customer_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.CUSTOMER_MANAGE)),
) -> CustomerRead:
    service = CustomerService(session)
    customer = await service.activate_customer(customer_id, actor_id=actor.user_id)
    await session.commit()
    return CustomerRead.model_validate(customer)
