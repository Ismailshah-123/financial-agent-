"""
app.repositories.payment_repository
======================================
Outgoing Payment data access. `get_by_invoice_id` enforces the
foundation-phase 1:1 invoice-to-payment rule at the query layer (see
`app.db.models.payment` docstring on why batching isn't modeled yet) —
services use it to check "has a payment already been scheduled for this
invoice" before creating a new one.

`list_other_executed_payments_same_vendor_and_amount` exists for
`FraudDetectionService`'s duplicate-payment signal — see that service's
module docstring.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import selectinload

from app.db.models.enums import PaymentStatus
from app.db.models.payment import OutgoingPayment
from app.repositories.base_repository import BaseRepository


class PaymentRepository(BaseRepository[OutgoingPayment]):
    model = OutgoingPayment

    async def get_by_invoice_id(self, invoice_id: uuid.UUID) -> OutgoingPayment | None:
        stmt = self._base_select().where(OutgoingPayment.invoice_id == invoice_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_invoice_ids(self, invoice_ids: list[uuid.UUID]) -> list[OutgoingPayment]:
        """Bulk lookup for `APPriorityService`: one query for every
        SCHEDULED_FOR_PAYMENT invoice's payment row, instead of
        `get_by_invoice_id` called once per invoice. Returns at most
        one row per id (the 1:1 rule `get_by_invoice_id`'s own
        docstring already documents), so callers can safely build a
        `{invoice_id: payment}` dict from the result."""
        if not invoice_ids:
            return []
        stmt = self._base_select().where(OutgoingPayment.invoice_id.in_(invoice_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_executed_since(self, *, since: date) -> list[OutgoingPayment]:
        """EXECUTED payments with executed_date >= since, for the AP
        payment-priority feature's "already executed" view. Bounded by
        `since` deliberately — this is the one query in this repository
        with no caller-supplied upper bound on result size otherwise,
        and full payment history isn't what that view needs (see
        app.services.ap_priority_calculations module docstring)."""
        stmt = (
            self._base_select()
            .where(
                OutgoingPayment.status == PaymentStatus.EXECUTED.value,
                OutgoingPayment.executed_date.is_not(None),
                OutgoingPayment.executed_date >= since,
            )
            .options(selectinload(OutgoingPayment.invoice), selectinload(OutgoingPayment.vendor))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_scheduled_for_date(
        self, scheduled_date: date, *, offset: int = 0, limit: int = 25
    ) -> list[OutgoingPayment]:
        stmt = (
            self._base_select()
            .where(
                OutgoingPayment.scheduled_date == scheduled_date,
                OutgoingPayment.status == PaymentStatus.SCHEDULED.value,
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_scheduled_within_range(
        self, *, start_date: date, end_date: date
    ) -> list[OutgoingPayment]:
        """SCHEDULED payments with scheduled_date within [start_date,
        end_date] — the committed-outflow side of
        TreasuryService.forecast_cash_flow. Deliberately status=
        SCHEDULED only, not APPROVED-but-unscheduled AP invoices — see
        that service's module docstring for why."""
        stmt = self._base_select().where(
            OutgoingPayment.scheduled_date >= start_date,
            OutgoingPayment.scheduled_date <= end_date,
            OutgoingPayment.status == PaymentStatus.SCHEDULED.value,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_other_executed_payments_same_vendor_and_amount(
        self,
        *,
        vendor_id: uuid.UUID,
        amount: Decimal,
        around_date: date,
        exclude_payment_id: uuid.UUID,
        window_days: int = 7,
    ) -> list[OutgoingPayment]:
        """Other EXECUTED payments to the same vendor, for the same
        amount, within `window_days` of `around_date` — a same-vendor,
        same-amount, close-together pair is the classic accidental (or
        fraudulent) duplicate-payment pattern. `exclude_payment_id`
        keeps a payment from matching itself."""
        window_start = around_date - timedelta(days=window_days)
        window_end = around_date + timedelta(days=window_days)
        stmt = self._base_select().where(
            OutgoingPayment.vendor_id == vendor_id,
            OutgoingPayment.amount == amount,
            OutgoingPayment.status == PaymentStatus.EXECUTED.value,
            OutgoingPayment.id != exclude_payment_id,
            OutgoingPayment.executed_date.is_not(None),
            OutgoingPayment.executed_date >= window_start,
            OutgoingPayment.executed_date <= window_end,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


    async def get_by_id_for_update(self, id_: uuid.UUID) -> OutgoingPayment | None:
        stmt = self._base_select().where(OutgoingPayment.id == id_).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
