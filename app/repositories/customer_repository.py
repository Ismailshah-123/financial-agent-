"""
app.repositories.customer_repository
=======================================
Customer data access — the AR mirror of `VendorRepository`. Adds
lookups the AR workflow needs beyond generic CRUD: finding a customer by
tax id (duplicate detection during onboarding, same rationale as
`VendorRepository.get_by_tax_id`) and by SAP Business Partner code
(Phase 2 sync reconciliation).
"""

from __future__ import annotations

from app.db.models.customer import Customer
from app.repositories.base_repository import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    model = Customer

    async def get_by_tax_id(self, tax_id: str) -> Customer | None:
        stmt = self._base_select().where(Customer.tax_id == tax_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_sap_business_partner_code(self, code: str) -> Customer | None:
        stmt = self._base_select().where(Customer.sap_business_partner_code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
