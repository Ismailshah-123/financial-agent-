"""
app.services.vendor_service
==============================
Use-case layer for Vendor management. Thin today (mostly delegates to
`VendorRepository`) but this is where vendor-onboarding business rules
live as the platform grows: duplicate-tax-id rejection, bank-account
change verification workflows (a classic vendor-fraud vector — a
"vendor" emailing in a new IBAN is one of the most common invoice-fraud
patterns in real AP departments), and the SAP Business Partner sync
hook (Phase 2).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.core.logging import get_audit_logger, get_logger
from app.db.models.enums import VendorStatus
from app.db.models.vendor import Vendor
from app.repositories.vendor_repository import VendorRepository
from app.schemas.vendor import VendorCreate, VendorUpdate

logger = get_logger(__name__)


class VendorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = VendorRepository(session)

    async def create_vendor(self, payload: VendorCreate, *, actor_id: str) -> Vendor:
        if payload.tax_id:
            existing = await self.repository.get_by_tax_id(payload.tax_id)
            if existing is not None:
                raise ConflictError(
                    f"A vendor with tax id '{payload.tax_id}' already exists.",
                    details={"existing_vendor_id": str(existing.id)},
                )

        vendor = Vendor(
            **payload.model_dump(exclude={"default_currency"}),
            default_currency=payload.default_currency.value,
            status=VendorStatus.PENDING_REVIEW.value,
            created_by_id=uuid.UUID(actor_id) if _is_uuid(actor_id) else None,
        )
        vendor = await self.repository.add(vendor)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="vendor.create",
            resource_type="vendor",
            resource_id=str(vendor.id),
            outcome="success",
            metadata={"name": vendor.name, "status": vendor.status},
        )
        logger.info("vendor_created", vendor_id=str(vendor.id), name=vendor.name)
        return vendor

    async def update_vendor(
        self, vendor_id: uuid.UUID, payload: VendorUpdate, *, actor_id: str
    ) -> Vendor:
        vendor = await self.repository.get_by_id_or_raise(vendor_id)
        update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
        if "default_currency" in update_data:
            update_data["default_currency"] = update_data["default_currency"].value
        vendor = await self.repository.update(vendor, **update_data)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="vendor.update",
            resource_type="vendor",
            resource_id=str(vendor.id),
            outcome="success",
            metadata={"updated_fields": list(update_data.keys())},
        )
        return vendor

    async def activate_vendor(self, vendor_id: uuid.UUID, *, actor_id: str) -> Vendor:
        """Moves a vendor out of PENDING_REVIEW. Deliberately a separate,
        narrow method (not a generic status field in VendorUpdate) since
        activating a vendor is a compliance decision, not a routine edit."""
        vendor = await self.repository.get_by_id_or_raise(vendor_id)
        vendor = await self.repository.update(vendor, status=VendorStatus.ACTIVE.value)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="vendor.activate",
            resource_type="vendor",
            resource_id=str(vendor.id),
            outcome="success",
        )
        return vendor

    async def apply_risk_assessment(
        self,
        vendor_id: uuid.UUID,
        *,
        risk_rating: int,
        new_status: VendorStatus | None,
        reason: str,
        actor_id: str,
    ) -> Vendor:
        """Applies a human-reviewed fraud/risk assessment — same
        "separate, narrow method" reasoning as activate_vendor. Never
        called by FraudDetectionAgent itself (it only recommends; see
        that agent's module docstring); this is what a human calls
        after reviewing the recommendation, same "AI never transacts
        without approval" rule as everywhere else in this platform.

        `new_status` is optional: a risk_rating update on its own
        (e.g. bumping it up after a MEDIUM finding) doesn't necessarily
        warrant a status change, whereas acting on a CRITICAL finding
        typically means also setting BLOCKED."""
        if not 0 <= risk_rating <= 100:
            raise ValidationError(f"risk_rating must be 0-100, got {risk_rating}.")

        vendor = await self.repository.get_by_id_or_raise(vendor_id)
        update_fields: dict = {"risk_rating": risk_rating}
        if new_status is not None:
            update_fields["status"] = new_status.value
        vendor = await self.repository.update(vendor, **update_fields)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="vendor.risk_assessment",
            resource_type="vendor",
            resource_id=str(vendor.id),
            outcome="success",
            metadata={
                "risk_rating": risk_rating,
                "new_status": new_status.value if new_status else None,
                "reason": reason,
            },
        )
        logger.info(
            "vendor_risk_assessment_applied",
            vendor_id=str(vendor.id),
            risk_rating=risk_rating,
            new_status=new_status.value if new_status else None,
        )
        return vendor

    async def get_vendor(self, vendor_id: uuid.UUID) -> Vendor:
        return await self.repository.get_by_id_or_raise(vendor_id)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
