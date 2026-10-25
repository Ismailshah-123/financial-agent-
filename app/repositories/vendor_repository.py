"""
app.repositories.vendor_repository
====================================
Vendor-specific data access on top of `BaseRepository`. Adds lookups the
AP workflow actually needs beyond generic CRUD: finding a vendor by tax
id (duplicate-vendor detection during onboarding) and by SAP Business
Partner code (Phase 2 sync reconciliation).
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models.vendor import Vendor
from app.repositories.base_repository import BaseRepository


class VendorRepository(BaseRepository[Vendor]):
    model = Vendor

    async def get_by_tax_id(self, tax_id: str) -> Vendor | None:
        stmt = self._base_select().where(Vendor.tax_id == tax_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_sap_business_partner_code(self, code: str) -> Vendor | None:
        stmt = self._base_select().where(Vendor.sap_business_partner_code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
