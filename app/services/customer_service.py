"""
app.services.customer_service
================================
Use-case layer for Customer management — the AR mirror of
`app.services.vendor_service`. Same shape deliberately: duplicate-tax-id
rejection at onboarding, PENDING_REVIEW default status, a narrow
`activate_customer` method rather than a generic status field on
`CustomerUpdate` (activating is a compliance decision, not a routine
edit — see `VendorService.activate_vendor` for the same reasoning).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.logging import get_audit_logger, get_logger
from app.db.models.customer import Customer
from app.db.models.enums import CustomerStatus
from app.repositories.customer_repository import CustomerRepository
from app.schemas.customer import CustomerCreate, CustomerUpdate

logger = get_logger(__name__)


class CustomerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CustomerRepository(session)

    async def create_customer(self, payload: CustomerCreate, *, actor_id: str) -> Customer:
        if payload.tax_id:
            existing = await self.repository.get_by_tax_id(payload.tax_id)
            if existing is not None:
                raise ConflictError(
                    f"A customer with tax id '{payload.tax_id}' already exists.",
                    details={"existing_customer_id": str(existing.id)},
                )

        customer = Customer(
            **payload.model_dump(exclude={"default_currency"}),
            default_currency=payload.default_currency.value,
            status=CustomerStatus.PENDING_REVIEW.value,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        customer = await self.repository.add(customer)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="customer.create",
            resource_type="customer",
            resource_id=str(customer.id),
            outcome="success",
            metadata={"name": customer.name, "status": customer.status},
        )
        logger.info("customer_created", customer_id=str(customer.id), name=customer.name)
        return customer

    async def update_customer(
        self, customer_id: uuid.UUID, payload: CustomerUpdate, *, actor_id: str
    ) -> Customer:
        customer = await self.repository.get_by_id_or_raise(customer_id)
        update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
        if "default_currency" in update_data:
            update_data["default_currency"] = update_data["default_currency"].value
        customer = await self.repository.update(customer, **update_data)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="customer.update",
            resource_type="customer",
            resource_id=str(customer.id),
            outcome="success",
            metadata={"updated_fields": list(update_data.keys())},
        )
        return customer

    async def activate_customer(self, customer_id: uuid.UUID, *, actor_id: str) -> Customer:
        customer = await self.repository.get_by_id_or_raise(customer_id)
        customer = await self.repository.update(customer, status=CustomerStatus.ACTIVE.value)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="customer.activate",
            resource_type="customer",
            resource_id=str(customer.id),
            outcome="success",
        )
        return customer

    async def get_customer(self, customer_id: uuid.UUID) -> Customer:
        return await self.repository.get_by_id_or_raise(customer_id)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
