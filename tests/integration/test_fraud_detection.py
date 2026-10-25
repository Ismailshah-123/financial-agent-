"""
Integration tests for FraudDetectionAgent and
VendorService.apply_risk_assessment, against real Postgres and the real
API.

Every vendor created through the API gets created_at = now, so a fresh
vendor always triggers the "new_vendor_payment" signal (within
NEW_VENDOR_WINDOW_DAYS of any payment made in the same test run) — this
isn't a test-isolation problem to work around, it's the realistic case
this suite mostly exercises. test_old_clean_vendor_is_low_risk
deliberately backdates a vendor's created_at directly via
_TestSessionFactory (same technique test_period_close.py uses for
backdated postings) to prove the LOW-risk, no-signals path too.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.db.models.vendor import Vendor
from tests.integration.conftest import _TestSessionFactory
from tests.integration.helpers import auth_headers, register_and_login

pytestmark = pytest.mark.asyncio


async def _get_executed_payment(client: AsyncClient, ap_headers: dict, *, suffix: str) -> dict:
    """Full vendor -> PO -> GRPO -> invoice -> approve -> execute flow,
    returning the executed OutgoingPayment. Mirrors
    test_ap_flow.py::test_full_ap_flow_happy_path exactly."""
    approver_token = await register_and_login(
        client, unique_suffix=f"{suffix}-approver", role="finance_director"
    )
    approver_headers = auth_headers(approver_token)

    vendor_response = await client.post(
        "/api/v1/vendors",
        headers=ap_headers,
        json={"name": f"Fraud Test Vendor {suffix}", "payment_terms_days": 30},
    )
    assert vendor_response.status_code == 201, vendor_response.text
    vendor = vendor_response.json()

    # ap_clerk can create a vendor but not activate one (VENDOR_MANAGE
    # is finance_director-only) — same separation-of-duties pattern as
    # invoice approval below.
    activate_response = await client.post(
        f"/api/v1/vendors/{vendor['id']}/activate", headers=approver_headers
    )
    assert activate_response.status_code == 200, activate_response.text

    po_response = await client.post(
        "/api/v1/purchase-orders",
        headers=ap_headers,
        json={
            "po_number": f"PO-FRAUD-{suffix}",
            "vendor_id": vendor["id"],
            "currency": "USD",
            "order_date": date.today().isoformat(),
            "lines": [
                {"line_number": 1, "description": "Widgets", "quantity_ordered": "10", "unit_price": "100.00"}
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
            "grpo_number": f"GRPO-FRAUD-{suffix}",
            "purchase_order_id": po["id"],
            "received_date": date.today().isoformat(),
            "lines": [{"purchase_order_line_id": po_line_id, "quantity_received": "10"}],
        },
    )
    assert grpo_response.status_code == 201, grpo_response.text

    invoice_response = await client.post(
        "/api/v1/invoices",
        headers=ap_headers,
        json={
            "invoice_number": f"INV-FRAUD-{suffix}",
            "vendor_id": vendor["id"],
            "purchase_order_id": po["id"],
            "currency": "USD",
            "subtotal": "1000.00",
            "tax_amount": "0",
            "total_amount": "1000.00",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "lines": [
                {
                    "line_number": 1,
                    "purchase_order_line_id": po_line_id,
                    "description": "Widgets",
                    "quantity": "10",
                    "unit_price": "100.00",
                }
            ],
        },
    )
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()

    approver_headers = auth_headers(approver_token)
    approve_response = await client.post(
        f"/api/v1/invoices/{invoice['id']}/approve", headers=approver_headers
    )
    assert approve_response.status_code == 200, approve_response.text

    payment_response = await client.post(
        "/api/v1/payments",
        headers=ap_headers,
        json={
            "invoice_id": invoice["id"],
            "payment_method": "bank_transfer",
            "scheduled_date": date.today().isoformat(),
        },
    )
    assert payment_response.status_code == 201, payment_response.text
    payment = payment_response.json()

    execute_response = await client.post(
        f"/api/v1/payments/{payment['id']}/execute", headers=approver_headers
    )
    assert execute_response.status_code == 200, execute_response.text
    return {
        "payment": execute_response.json(),
        "vendor": vendor,
        "approver_headers": approver_headers,
    }


async def test_fresh_vendor_payment_flags_new_vendor_signal(
    client: AsyncClient, unique_suffix: str
) -> None:
    ap_token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    ap_headers = auth_headers(ap_token)
    result = await _get_executed_payment(client, ap_headers, suffix=unique_suffix)

    agent_response = await client.post(
        "/api/v1/agents/fraud-detection/run",
        headers=result["approver_headers"],
        json={"payment_id": result["payment"]["id"]},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    assert decision["risk_level"] == "medium"
    assert decision["requires_approval"] is True
    assert decision["financial_impact"]["amount"] == "1000.00"
    assert "new_vendor" in str(decision["relevant_policies"])


async def test_blocked_vendor_is_critical(client: AsyncClient, unique_suffix: str) -> None:
    ap_token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    ap_headers = auth_headers(ap_token)
    result = await _get_executed_payment(client, ap_headers, suffix=unique_suffix)

    block_response = await client.post(
        f"/api/v1/vendors/{result['vendor']['id']}/risk-assessment",
        headers=result["approver_headers"],
        json={"risk_rating": 95, "new_status": "blocked", "reason": "test: suspected fraud"},
    )
    assert block_response.status_code == 200, block_response.text
    assert block_response.json()["status"] == "blocked"
    assert block_response.json()["risk_rating"] == 95

    agent_response = await client.post(
        "/api/v1/agents/fraud-detection/run",
        headers=result["approver_headers"],
        json={"payment_id": result["payment"]["id"]},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]
    assert decision["risk_level"] == "critical"


async def test_old_clean_vendor_is_low_risk(client: AsyncClient, unique_suffix: str) -> None:
    ap_token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    ap_headers = auth_headers(ap_token)
    result = await _get_executed_payment(client, ap_headers, suffix=unique_suffix)

    # Backdate the vendor so neither "new vendor" nor "recently
    # modified" fires — same direct-session technique
    # test_period_close.py uses for backdated postings.
    long_ago = datetime.now(timezone.utc) - timedelta(days=400)
    async with _TestSessionFactory() as session:
        await session.execute(
            update(Vendor)
            .where(Vendor.id == result["vendor"]["id"])
            .values(created_at=long_ago, updated_at=long_ago)
        )
        await session.commit()

    agent_response = await client.post(
        "/api/v1/agents/fraud-detection/run",
        headers=result["approver_headers"],
        json={"payment_id": result["payment"]["id"]},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    assert decision["risk_level"] == "low"
    assert decision["requires_approval"] is False
    assert decision["financial_impact"] is None
    assert "No fraud signals detected" in decision["reasoning"]


async def test_ap_clerk_cannot_apply_risk_assessment(
    client: AsyncClient, unique_suffix: str
) -> None:
    ap_token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    ap_headers = auth_headers(ap_token)
    vendor_response = await client.post(
        "/api/v1/vendors",
        headers=ap_headers,
        json={"name": f"Perm Test Vendor {unique_suffix}", "payment_terms_days": 30},
    )
    assert vendor_response.status_code == 201, vendor_response.text
    vendor = vendor_response.json()

    response = await client.post(
        f"/api/v1/vendors/{vendor['id']}/risk-assessment",
        headers=ap_headers,
        json={"risk_rating": 80, "reason": "test"},
    )
    assert response.status_code == 403
