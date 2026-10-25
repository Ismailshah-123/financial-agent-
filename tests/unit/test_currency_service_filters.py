"""Service-level filtering and pagination tests for currency-grouped summaries."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import uuid

import pytest

from app.services.aging_calculations import compute_invoice_aging, summarize_customer_aging
from app.services.aging_service import AgingService
from app.services.ap_priority_calculations import (
    PaymentPriorityStatus,
    compute_payment_obligation,
)
from app.services.ap_priority_service import APPriorityService

_AS_OF = date(2026, 10, 1)


def _invoice(*, customer_id: uuid.UUID, customer_name: str, currency: str, amount: str, due_date: date):
    return compute_invoice_aging(
        invoice_id=uuid.uuid4(),
        invoice_number=f"INV-{customer_name}-{currency}",
        customer_id=customer_id,
        customer_name=customer_name,
        invoice_date=date(2026, 1, 1),
        due_date=due_date,
        total_amount=Decimal(amount),
        amount_paid=Decimal("0"),
        amount_credited=Decimal("0"),
        currency=currency,
        status="approved",
        as_of=_AS_OF,
    )


def _customer_summary(*, customer_id: uuid.UUID, customer_name: str, invoices, default_currency: str):
    return summarize_customer_aging(
        customer_id=customer_id,
        customer_name=customer_name,
        currency=default_currency,
        credit_limit=None,
        invoices=invoices,
        as_of=_AS_OF,
    )


def _obligation(*, vendor_id: uuid.UUID, vendor_name: str, currency: str, amount: str):
    return compute_payment_obligation(
        invoice_id=uuid.uuid4(),
        invoice_number=f"AP-{vendor_name}-{currency}",
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        amount=Decimal(amount),
        currency=currency,
        due_date=date(2026, 10, 20),
        as_of=_AS_OF,
        status=PaymentPriorityStatus.READY_TO_SCHEDULE,
    )


@pytest.mark.asyncio
async def test_customer_minimum_filter_and_pagination_use_currency_groups():
    mixed_id = uuid.uuid4()
    single_id = uuid.uuid4()
    mixed = _customer_summary(
        customer_id=mixed_id,
        customer_name="Multi Currency Customer",
        invoices=[
            _invoice(customer_id=mixed_id, customer_name="Multi Currency Customer", currency="USD", amount="100.00", due_date=date(2026, 9, 1)),
            _invoice(customer_id=mixed_id, customer_name="Multi Currency Customer", currency="EUR", amount="150.00", due_date=date(2026, 9, 20)),
        ],
        default_currency="PKR",
    )
    single = _customer_summary(
        customer_id=single_id,
        customer_name="Single Currency Customer",
        invoices=[
            _invoice(customer_id=single_id, customer_name="Single Currency Customer", currency="PKR", amount="200.00", due_date=date(2026, 3, 1)),
        ],
        default_currency="PKR",
    )
    assert mixed.total_outstanding is None
    service = AgingService(session=None)

    async def build_summaries(*, as_of):
        assert as_of == _AS_OF
        return [mixed, single]

    service._build_customer_summaries = build_summaries
    first_page, total = await service.list_customer_aging(
        as_of=_AS_OF, minimum_amount=Decimal("150.00"), offset=0, limit=1
    )
    second_page, second_total = await service.list_customer_aging(
        as_of=_AS_OF, minimum_amount=Decimal("150.00"), offset=1, limit=1
    )
    assert total == second_total == 2
    assert len(first_page) == len(second_page) == 1
    assert first_page[0].customer_id != second_page[0].customer_id
    assert {first_page[0].customer_id, second_page[0].customer_id} == {mixed_id, single_id}

    searched, searched_total = await service.list_customer_aging(
        as_of=_AS_OF, minimum_amount=Decimal("150.00"), search="Multi Currency", limit=10
    )
    assert searched_total == 1
    assert searched[0].customer_id == mixed_id


@pytest.mark.asyncio
async def test_vendor_search_and_pagination_preserve_currency_grouped_exposure():
    mixed_id = uuid.uuid4()
    single_id = uuid.uuid4()
    obligations = [
        _obligation(vendor_id=mixed_id, vendor_name="Multi Currency Vendor", currency="USD", amount="100.00"),
        _obligation(vendor_id=mixed_id, vendor_name="Multi Currency Vendor", currency="EUR", amount="150.00"),
        _obligation(vendor_id=single_id, vendor_name="Single Currency Vendor", currency="PKR", amount="500.00"),
    ]
    service = APPriorityService(session=None)

    async def build_obligations(*, as_of, executed_since):
        assert as_of == _AS_OF
        assert executed_since is None
        return obligations

    service._build_obligations = build_obligations
    first_page, total = await service.list_vendor_exposure(as_of=_AS_OF, offset=0, limit=1)
    second_page, second_total = await service.list_vendor_exposure(as_of=_AS_OF, offset=1, limit=1)
    assert total == second_total == 2
    assert len(first_page) == len(second_page) == 1
    assert first_page[0].vendor_id != second_page[0].vendor_id
    mixed = next(item for item in [first_page[0], second_page[0]] if item.vendor_id == mixed_id)
    assert mixed.total_exposure is None
    assert {balance.currency: balance.total_exposure for balance in mixed.currency_balances} == {
        "EUR": Decimal("150.00"),
        "USD": Decimal("100.00"),
    }

    searched, searched_total = await service.list_vendor_exposure(
        as_of=_AS_OF, search="Multi Currency", offset=0, limit=10
    )
    assert searched_total == 1
    assert searched[0].vendor_id == mixed_id
