"""
app.repositories.credit_memo_repository
==========================================
Data access for both `ARCreditMemo` and `APCreditMemo` — kept in one
file since the two repositories are nearly identical (mirroring how
`app.db.models.credit_memo` keeps both models in one file), unlike most
other repositories which get their own file.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import selectinload

from app.db.models.credit_memo import APCreditMemo, ARCreditMemo
from app.repositories.base_repository import BaseRepository


class ARCreditMemoRepository(BaseRepository[ARCreditMemo]):
    model = ARCreditMemo

    async def get_by_id_with_lines(self, id_: uuid.UUID) -> ARCreditMemo | None:
        stmt = (
            self._base_select()
            .where(ARCreditMemo.id == id_)
            .options(selectinload(ARCreditMemo.lines))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    async def get_by_id_with_lines_for_update(self, id_: uuid.UUID) -> ARCreditMemo | None:
        stmt = (
            self._base_select()
            .where(ARCreditMemo.id == id_)
            .with_for_update().options(selectinload(ARCreditMemo.lines))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_customer(self, customer_id: uuid.UUID) -> list[ARCreditMemo]:
        stmt = self._base_select().where(ARCreditMemo.customer_id == customer_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_ar_invoice(self, ar_invoice_id: uuid.UUID) -> list[ARCreditMemo]:
        stmt = self._base_select().where(ARCreditMemo.related_ar_invoice_id == ar_invoice_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class APCreditMemoRepository(BaseRepository[APCreditMemo]):
    model = APCreditMemo

    async def get_by_id_with_lines(self, id_: uuid.UUID) -> APCreditMemo | None:
        stmt = (
            self._base_select()
            .where(APCreditMemo.id == id_)
            .options(selectinload(APCreditMemo.lines))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_vendor(self, vendor_id: uuid.UUID) -> list[APCreditMemo]:
        stmt = self._base_select().where(APCreditMemo.vendor_id == vendor_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_invoice(self, invoice_id: uuid.UUID) -> list[APCreditMemo]:
        stmt = self._base_select().where(APCreditMemo.related_invoice_id == invoice_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
