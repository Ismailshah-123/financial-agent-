"""
app.repositories.incoming_payment_repository
===============================================
Incoming Payment data access. `list_by_ar_invoice` returns a list, not
`get_by_ar_invoice_id` returning a single row, because — unlike
`PaymentRepository.get_by_invoice_id` on the AP side — an AR invoice can
legitimately have multiple incoming payments applied to it (partial
payments over time). See `app.db.models.incoming_payment`'s docstring.
"""

from __future__ import annotations

import uuid

from app.db.models.incoming_payment import IncomingPayment
from app.repositories.base_repository import BaseRepository


class IncomingPaymentRepository(BaseRepository[IncomingPayment]):
    model = IncomingPayment

    async def list_by_ar_invoice(self, ar_invoice_id: uuid.UUID) -> list[IncomingPayment]:
        stmt = self._base_select().where(IncomingPayment.ar_invoice_id == ar_invoice_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_customer(self, customer_id: uuid.UUID) -> list[IncomingPayment]:
        stmt = self._base_select().where(IncomingPayment.customer_id == customer_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
