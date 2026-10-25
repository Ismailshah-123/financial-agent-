"""
Integration tests for the approval inbox, against real Postgres.

Deliberately triggers a REAL agent run (Fraud Detection, via a fresh
vendor + payment — a scenario already established elsewhere in this
suite as reliably producing a MEDIUM-risk, requires_approval=True
decision) rather than seeding an ApprovalRequestRecord directly. The
point being tested is that `BaseAgent.run()`'s new persistence hook
actually fires for a real agent, not just that the API layer can list/
approve/reject rows that already exist.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.integration.helpers import auth_headers, register_and_login

pytestmark = pytest.mark.asyncio


async def _create_executed_payment_for_fresh_vendor(
    client: AsyncClient, ap_headers: dict, approver_headers: dict, *, suffix: str
) -> str:
    """Mirrors test_fraud_detection.py's _get_executed_payment — a
    fresh vendor's payment reliably produces a MEDIUM-risk,
    requires_approval=True Fraud Detection decision."""
    vendor_response = await client.post(
        "/api/v1/vendors",
        headers=ap_headers,
        json={"name": f"Inbox Test Vendor {suffix}", "payment_terms_days": 30},
    )
    assert vendor_response.status_code == 201, vendor_response.text
    vendor = vendor_response.json()
    await client.post(f"/api/v1/vendors/{vendor['id']}/activate", headers=approver_headers)

    po_response = await client.post(
        "/api/v1/purchase-orders",
        headers=ap_headers,
        json={
            "po_number": f"PO-INBOX-{suffix}",
            "vendor_id": vendor["id"],
            "currency": "USD",
            "order_date": date.today().isoformat(),
            "lines": [
                {"line_number": 1, "description": "Widgets", "quantity_ordered": "1", "unit_price": "500.00"}
            ],
        },
    )
    po = po_response.json()
    po_line_id = po["lines"][0]["id"]

    grpo_response = await client.post(
        "/api/v1/goods-receipts",
        headers=ap_headers,
        json={
            "grpo_number": f"GRPO-INBOX-{suffix}",
            "purchase_order_id": po["id"],
            "received_date": date.today().isoformat(),
            "lines": [{"purchase_order_line_id": po_line_id, "quantity_received": "1"}],
        },
    )
    assert grpo_response.status_code == 201, grpo_response.text

    invoice_response = await client.post(
        "/api/v1/invoices",
        headers=ap_headers,
        json={
            "invoice_number": f"INV-INBOX-{suffix}",
            "vendor_id": vendor["id"],
            "purchase_order_id": po["id"],
            "currency": "USD",
            "subtotal": "500.00",
            "tax_amount": "0",
            "total_amount": "500.00",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "lines": [
                {
                    "line_number": 1,
                    "purchase_order_line_id": po_line_id,
                    "description": "Widgets",
                    "quantity": "1",
                    "unit_price": "500.00",
                }
            ],
        },
    )
    invoice = invoice_response.json()
    await client.post(f"/api/v1/invoices/{invoice['id']}/approve", headers=approver_headers)

    payment_response = await client.post(
        "/api/v1/payments",
        headers=ap_headers,
        json={
            "invoice_id": invoice["id"],
            "payment_method": "bank_transfer",
            "scheduled_date": date.today().isoformat(),
        },
    )
    payment = payment_response.json()
    execute_response = await client.post(
        f"/api/v1/payments/{payment['id']}/execute", headers=approver_headers
    )
    assert execute_response.status_code == 200, execute_response.text
    return execute_response.json()["id"]


async def test_agent_run_creates_a_listable_pending_approval(
    client: AsyncClient, unique_suffix: str
) -> None:
    ap_token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    ap_headers = auth_headers(ap_token)
    director_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-director", role="finance_director"
    )
    director_headers = auth_headers(director_token)

    payment_id = await _create_executed_payment_for_fresh_vendor(
        client, ap_headers, director_headers, suffix=unique_suffix
    )

    agent_response = await client.post(
        "/api/v1/agents/fraud-detection/run",
        headers=director_headers,
        json={"payment_id": payment_id},
    )
    assert agent_response.status_code == 200, agent_response.text
    assert agent_response.json()["decisions"][0]["requires_approval"] is True

    inbox_response = await client.get(
        "/api/v1/approval-requests", headers=director_headers, params={"agent_type": "fraud_detection"}
    )
    assert inbox_response.status_code == 200, inbox_response.text
    matching = [r for r in inbox_response.json() if payment_id in str(r["decision"])]
    assert len(matching) == 1
    record = matching[0]
    assert record["status"] == "pending"
    assert record["agent_type"] == "fraud_detection"
    assert record["decision"]["risk_level"] == "medium"


async def test_approve_then_reject_lifecycle(client: AsyncClient, unique_suffix: str) -> None:
    ap_token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    ap_headers = auth_headers(ap_token)
    director_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-director", role="finance_director"
    )
    director_headers = auth_headers(director_token)

    payment_id = await _create_executed_payment_for_fresh_vendor(
        client, ap_headers, director_headers, suffix=unique_suffix
    )
    await client.post(
        "/api/v1/agents/fraud-detection/run", headers=director_headers, json={"payment_id": payment_id}
    )

    inbox = await client.get(
        "/api/v1/approval-requests", headers=director_headers, params={"agent_type": "fraud_detection"}
    )
    record = next(r for r in inbox.json() if payment_id in str(r["decision"]))

    approve_response = await client.post(
        f"/api/v1/approval-requests/{record['id']}/approve",
        headers=director_headers,
        json={"notes": "reviewed, looks fine"},
    )
    assert approve_response.status_code == 200, approve_response.text
    approved = approve_response.json()
    assert approved["status"] == "approved"
    assert approved["resolved_by_id"] is not None
    assert approved["resolution_notes"] == "reviewed, looks fine"

    # Already resolved -> approving again is a conflict.
    second_approve = await client.post(
        f"/api/v1/approval-requests/{record['id']}/approve", headers=director_headers, json={}
    )
    assert second_approve.status_code == 409

    # No longer in the pending list.
    inbox_after = await client.get(
        "/api/v1/approval-requests", headers=director_headers, params={"agent_type": "fraud_detection"}
    )
    assert record["id"] not in [r["id"] for r in inbox_after.json()]


async def test_reject_without_reason_is_rejected(client: AsyncClient, unique_suffix: str) -> None:
    ap_token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    ap_headers = auth_headers(ap_token)
    director_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-director", role="finance_director"
    )
    director_headers = auth_headers(director_token)

    payment_id = await _create_executed_payment_for_fresh_vendor(
        client, ap_headers, director_headers, suffix=unique_suffix
    )
    await client.post(
        "/api/v1/agents/fraud-detection/run", headers=director_headers, json={"payment_id": payment_id}
    )
    inbox = await client.get(
        "/api/v1/approval-requests", headers=director_headers, params={"agent_type": "fraud_detection"}
    )
    record = next(r for r in inbox.json() if payment_id in str(r["decision"]))

    response = await client.post(
        f"/api/v1/approval-requests/{record['id']}/reject",
        headers=director_headers,
        json={"reason": "   "},
    )
    assert response.status_code == 422, response.text


async def test_ap_clerk_cannot_read_or_action_approval_inbox(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)
    response = await client.get("/api/v1/approval-requests", headers=headers)
    assert response.status_code == 403


async def test_auditor_can_read_but_not_action(client: AsyncClient, unique_suffix: str) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="auditor")
    headers = auth_headers(token)

    read_response = await client.get("/api/v1/approval-requests", headers=headers)
    assert read_response.status_code == 200

    fake_id = "00000000-0000-0000-0000-000000000000"
    action_response = await client.post(
        f"/api/v1/approval-requests/{fake_id}/approve", headers=headers, json={}
    )
    assert action_response.status_code == 403
