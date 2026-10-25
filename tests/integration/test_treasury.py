"""
Integration tests for TreasuryAgent, against real Postgres and the
real API.

DATE ISOLATION: uses November 2026 throughout — a range nothing else
in this suite touches (other tests use "today", or January/February/
March 2026 for test_period_close.py) — so the seeded cash balance and
events here can't collide with anything else. The starting cash
balance is established by posting directly via PostingService (same
technique test_period_close.py and test_fraud_detection.py use), since
there's no API path to backdate a cash-affecting posting.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.constants import Currency, TransactionType
from app.services.posting_service import DefaultAccounts, PostingLine, PostingService
from tests.integration.conftest import _TestSessionFactory
from tests.integration.helpers import auth_headers, register_and_login

pytestmark = pytest.mark.asyncio

_AS_OF = date(2026, 11, 1)


async def _seed_cash_balance(amount: Decimal) -> None:
    async with _TestSessionFactory() as session:
        posting_service = PostingService(session)
        await posting_service.post(
            transaction_type=TransactionType.AR_INVOICE,
            reference_id=uuid.uuid4(),
            posting_date=_AS_OF,
            currency=Currency.USD,
            lines=[
                PostingLine(account_code=DefaultAccounts.CASH, debit=amount),
                PostingLine(account_code=DefaultAccounts.REVENUE, credit=amount),
            ],
            actor_id="00000000-0000-0000-0000-000000000000",
        )
        await session.commit()


async def test_forecast_with_scheduled_outflow_flags_high_risk(
    client: AsyncClient, unique_suffix: str
) -> None:
    await _seed_cash_balance(Decimal("100000.00"))

    ap_token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    ap_headers = auth_headers(ap_token)
    director_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-director", role="finance_director"
    )
    director_headers = auth_headers(director_token)

    # --- A scheduled AP outflow of 9500 on day 15 of the horizon ---
    vendor_response = await client.post(
        "/api/v1/vendors",
        headers=ap_headers,
        json={"name": f"Treasury Test Vendor {unique_suffix}", "payment_terms_days": 30},
    )
    assert vendor_response.status_code == 201, vendor_response.text
    vendor = vendor_response.json()
    await client.post(f"/api/v1/vendors/{vendor['id']}/activate", headers=director_headers)

    po_response = await client.post(
        "/api/v1/purchase-orders",
        headers=ap_headers,
        json={
            "po_number": f"PO-TREAS-{unique_suffix}",
            "vendor_id": vendor["id"],
            "currency": "USD",
            "order_date": _AS_OF.isoformat(),
            "lines": [
                {"line_number": 1, "description": "Equipment", "quantity_ordered": "1", "unit_price": "95000.00"}
            ],
        },
    )
    assert po_response.status_code == 201, po_response.text
    po = po_response.json()
    po_line_id = po["lines"][0]["id"]

    grpo_response = await client.post(
        "/api/v1/goods-receipts",
        headers=ap_headers,
        json={
            "grpo_number": f"GRPO-TREAS-{unique_suffix}",
            "purchase_order_id": po["id"],
            "received_date": _AS_OF.isoformat(),
            "lines": [{"purchase_order_line_id": po_line_id, "quantity_received": "1"}],
        },
    )
    assert grpo_response.status_code == 201, grpo_response.text

    invoice_response = await client.post(
        "/api/v1/invoices",
        headers=ap_headers,
        json={
            "invoice_number": f"INV-TREAS-{unique_suffix}",
            "vendor_id": vendor["id"],
            "purchase_order_id": po["id"],
            "currency": "USD",
            "subtotal": "95000.00",
            "tax_amount": "0",
            "total_amount": "95000.00",
            "invoice_date": _AS_OF.isoformat(),
            "due_date": (_AS_OF + timedelta(days=30)).isoformat(),
            "lines": [
                {
                    "line_number": 1,
                    "purchase_order_line_id": po_line_id,
                    "description": "Equipment",
                    "quantity": "1",
                    "unit_price": "95000.00",
                }
            ],
        },
    )
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()

    approve_response = await client.post(
        f"/api/v1/invoices/{invoice['id']}/approve", headers=director_headers
    )
    assert approve_response.status_code == 200, approve_response.text

    payment_response = await client.post(
        "/api/v1/payments",
        headers=ap_headers,
        json={
            "invoice_id": invoice["id"],
            "payment_method": "bank_transfer",
            "scheduled_date": (_AS_OF + timedelta(days=15)).isoformat(),
        },
    )
    assert payment_response.status_code == 201, payment_response.text
    # Deliberately NOT executed — SCHEDULED payments don't post to the
    # ledger (see PostingService docstring), but they DO show up in
    # the forecast as a committed future outflow.

    # --- An AR inflow of 2000 on day 20 ---
    ar_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-ar", role="ar_clerk"
    )
    ar_headers = auth_headers(ar_token)
    customer_response = await client.post(
        "/api/v1/customers",
        headers=ar_headers,
        json={"name": f"Treasury Test Customer {unique_suffix}", "payment_terms_days": 30},
    )
    assert customer_response.status_code == 201, customer_response.text
    customer = customer_response.json()

    ar_invoice_response = await client.post(
        "/api/v1/ar-invoices",
        headers=ar_headers,
        json={
            "invoice_number": f"ARINV-TREAS-{unique_suffix}",
            "customer_id": customer["id"],
            "currency": "USD",
            "subtotal": "20000.00",
            "tax_amount": "0",
            "total_amount": "20000.00",
            "invoice_date": _AS_OF.isoformat(),
            "due_date": (_AS_OF + timedelta(days=20)).isoformat(),
            "lines": [
                {"line_number": 1, "description": "Services", "quantity": "1", "unit_price": "20000.00"}
            ],
        },
    )
    assert ar_invoice_response.status_code == 201, ar_invoice_response.text

    # --- Run the forecast ---
    agent_response = await client.post(
        "/api/v1/agents/treasury/run",
        headers=director_headers,
        json={"as_of": _AS_OF.isoformat(), "horizon_days": 30},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    # 100000 start -95000 (day15) = 5000 lowest, then +20000 (day20) = 25000 end.
    # 5000/100000 = 5% < HIGH_RISK_BUFFER_RATIO (10%) -> high.
    # (Scaled 10x from an earlier version of this test that used 10000/
    # 9500/2000: get_current_cash_balance is correctly cumulative-since-
    # inception for an asset account — cash is never "closed" the way
    # Revenue/Expense are (see PeriodCloseService) — so it legitimately
    # sweeps in every other test's today-dated payment activity in this
    # shared test database. A $500 margin was too thin once enough other
    # tests existed to execute a few thousand dollars of real payments;
    # $5,000 has enough headroom that this suite's ordinary growth won't
    # silently flip the risk tier again.)
    assert decision["risk_level"] == "high"
    assert decision["requires_approval"] is True
    assert len(decision["supporting_evidence"]) == 2


async def test_forecast_with_no_events_is_low_risk(
    client: AsyncClient, unique_suffix: str
) -> None:
    isolated_as_of = date(2026, 12, 1)  # a month nothing else touches
    async with _TestSessionFactory() as session:
        posting_service = PostingService(session)
        await posting_service.post(
            transaction_type=TransactionType.AR_INVOICE,
            reference_id=uuid.uuid4(),
            posting_date=isolated_as_of,
            currency=Currency.USD,
            lines=[
                PostingLine(account_code=DefaultAccounts.CASH, debit=Decimal("5000.00")),
                PostingLine(account_code=DefaultAccounts.REVENUE, credit=Decimal("5000.00")),
            ],
            actor_id="00000000-0000-0000-0000-000000000000",
        )
        await session.commit()

    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)

    agent_response = await client.post(
        "/api/v1/agents/treasury/run",
        headers=headers,
        json={"as_of": isolated_as_of.isoformat(), "horizon_days": 30},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    assert decision["risk_level"] == "low"
    assert decision["requires_approval"] is False
    assert decision["financial_impact"] is None
    assert "No inflow or outflow events" in decision["reasoning"]
