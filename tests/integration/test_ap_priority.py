"""
Integration tests for app.api.v1.ap_priority, following the exact
vendor -> invoice -> agent match -> approve -> schedule -> execute flow
tests/integration/test_ap_flow.py already proves works. Same "could not
be executed in this sandbox" caveat as tests/integration
/test_collections_agent.py's module docstring — read that one, it
applies here unchanged (no network, no project dependencies installed,
no Postgres reachable from this session).

Same shared-database caveat as test_collections_agent.py too:
GET /ap-priority/summary and /ap-priority/vendors aggregate every
vendor in the whole test database, so assertions against them look for
this test's own vendor_id/invoice rather than asserting a total.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from tests.integration.helpers import auth_headers, register_and_login


async def _create_vendor(client: AsyncClient, headers: dict, *, suffix: str) -> dict:
    response = await client.post(
        "/api/v1/vendors",
        headers=headers,
        json={"name": f"AP Priority Test Vendor {suffix}", "payment_terms_days": 30},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _ingest_invoice(
    client: AsyncClient, headers: dict, *, vendor_id: str, suffix: str, amount: str, due_date: date
) -> dict:
    response = await client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "invoice_number": f"APINV-{suffix}",
            "vendor_id": vendor_id,
            "currency": "PKR",
            "subtotal": amount,
            "tax_amount": "0",
            "total_amount": amount,
            "invoice_date": date.today().isoformat(),
            "due_date": due_date.isoformat(),
            "lines": [
                {"line_number": 1, "description": "Services", "quantity": "1", "unit_price": amount}
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _find(items: list[dict], *, id_key: str, value: str) -> dict:
    match = next((item for item in items if item[id_key] == value), None)
    assert match is not None, f"expected to find {id_key}={value} among {len(items)} item(s)"
    return match


async def test_invoice_moves_through_every_ap_priority_status_the_real_flow_produces(
    client: AsyncClient, unique_suffix: str
) -> None:
    ap_token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    ap_headers = auth_headers(ap_token)
    director_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-director", role="finance_director"
    )
    director_headers = auth_headers(director_token)

    vendor = await _create_vendor(client, ap_headers, suffix=unique_suffix)
    # Overdue on purpose: due 10 days ago, so once it's ready to schedule
    # it should already show as an OVERDUE obligation, not just "ready."
    due_date = date.today() - timedelta(days=10)
    invoice = await _ingest_invoice(
        client, ap_headers, vendor_id=vendor["id"], suffix=unique_suffix, amount="750.00", due_date=due_date
    )

    # --- RECEIVED: not a payable obligation yet, must not appear ---
    obligations = await client.get(
        "/api/v1/ap-priority/obligations",
        headers=ap_headers,
        params={"vendor_id": vendor["id"]},
    )
    assert obligations.status_code == 200, obligations.text
    assert obligations.json()["items"] == []

    # --- Run the AP agent: RECEIVED -> MATCHED (no PO -> manual match) ---
    agent_response = await client.post(
        "/api/v1/agents/accounts-payable/run", headers=ap_headers, json={"invoice_id": invoice["id"]}
    )
    assert agent_response.status_code == 200, agent_response.text

    # --- MATCHED -> this feature's AWAITING_APPROVAL, and already overdue ---
    obligations = await client.get(
        "/api/v1/ap-priority/obligations", headers=ap_headers, params={"vendor_id": vendor["id"]}
    )
    row = _find(obligations.json()["items"], id_key="invoice_id", value=invoice["id"])
    assert row["status"] == "awaiting_approval"
    assert row["due_bucket"] == "overdue"
    assert row["days_until_due"] == -10
    assert row["amount"] == "750.00"
    assert row["vendor_id"] == vendor["id"]
    # status_points(20) + overdue 8..30 days(45) = 65 -> high
    assert row["priority_score"] == 65
    assert row["priority"] == "high"

    # --- Approve: MATCHED -> APPROVED -> this feature's READY_TO_SCHEDULE ---
    approve_response = await client.post(
        f"/api/v1/invoices/{invoice['id']}/approve", headers=director_headers
    )
    assert approve_response.status_code == 200, approve_response.text

    obligations = await client.get(
        "/api/v1/ap-priority/obligations", headers=ap_headers, params={"vendor_id": vendor["id"]}
    )
    row = _find(obligations.json()["items"], id_key="invoice_id", value=invoice["id"])
    assert row["status"] == "ready_to_schedule"
    # status_points(0) + overdue 8..30 days(45) = 45 -> high
    assert row["priority_score"] == 45
    assert row["priority"] == "high"

    # --- And it shows up in vendor exposure, scoped to this vendor ---
    vendor_detail = await client.get(
        f"/api/v1/ap-priority/vendor/{vendor['id']}", headers=ap_headers
    )
    assert vendor_detail.status_code == 200, vendor_detail.text
    assert vendor_detail.json()["total_exposure"] == "750.00"
    assert vendor_detail.json()["overdue_amount"] == "750.00"
    assert vendor_detail.json()["highest_priority"] == "high"

    # --- Schedule payment: APPROVED -> SCHEDULED_FOR_PAYMENT, payment
    #     SCHEDULED -> this feature's SCHEDULED ---
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

    obligations = await client.get(
        "/api/v1/ap-priority/obligations", headers=ap_headers, params={"vendor_id": vendor["id"]}
    )
    row = _find(obligations.json()["items"], id_key="invoice_id", value=invoice["id"])
    assert row["status"] == "scheduled"
    assert row["scheduled_date"] == date.today().isoformat()

    # --- Execute payment: invoice -> PAID, payment -> EXECUTED ---
    execute_response = await client.post(
        f"/api/v1/payments/{payment['id']}/execute", headers=director_headers
    )
    assert execute_response.status_code == 200, execute_response.text

    # --- No longer a payable obligation at all ---
    obligations = await client.get(
        "/api/v1/ap-priority/obligations", headers=ap_headers, params={"vendor_id": vendor["id"]}
    )
    assert obligations.json()["items"] == []

    # --- But visible with include_executed=true, as EXECUTED ---
    executed_view = await client.get(
        "/api/v1/ap-priority/obligations",
        headers=ap_headers,
        params={"vendor_id": vendor["id"], "include_executed": "true"},
    )
    row = _find(executed_view.json()["items"], id_key="invoice_id", value=invoice["id"])
    assert row["status"] == "executed"
    assert row["priority"] is None
    assert row["priority_score"] is None
    assert row["executed_date"] == date.today().isoformat()

    # --- And vendor exposure is back to zero (EXECUTED excluded) ---
    vendor_detail = await client.get(
        f"/api/v1/ap-priority/vendor/{vendor['id']}", headers=ap_headers
    )
    assert vendor_detail.json()["total_exposure"] == "0.00"
    assert vendor_detail.json()["open_invoice_count"] == 0


async def test_ap_priority_summary_reflects_this_test_own_vendor(
    client: AsyncClient, unique_suffix: str
) -> None:
    ap_token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    ap_headers = auth_headers(ap_token)
    vendor = await _create_vendor(client, ap_headers, suffix=unique_suffix)
    invoice = await _ingest_invoice(
        client, ap_headers, vendor_id=vendor["id"], suffix=unique_suffix,
        amount="200.00", due_date=date.today() + timedelta(days=5),
    )
    await client.post(
        "/api/v1/agents/accounts-payable/run",
        headers=ap_headers,
        json={"invoice_id": invoice["id"]},
    )

    summary = await client.get("/api/v1/ap-priority/summary", headers=ap_headers)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["open_obligation_count"] >= 1
    assert "awaiting_approval" in body["by_status_count"]


async def test_unknown_vendor_returns_404(client: AsyncClient, unique_suffix: str) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)
    response = await client.get(f"/api/v1/ap-priority/vendor/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 404, response.text


async def test_ar_clerk_can_read_ap_priority(client: AsyncClient, unique_suffix: str) -> None:
    # Unlike AR_INVOICE_READ (which AP_CLERK lacks), INVOICE_READ (the
    # AP permission) is granted to AR_CLERK too — see ROLE_PERMISSIONS
    # in app.core.security. Pinning this so it reads as a deliberate
    # check, not an oversight if it looks surprising next to the
    # Collections RBAC test's asymmetric result.
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    headers = auth_headers(token)
    response = await client.get("/api/v1/ap-priority/summary", headers=headers)
    assert response.status_code == 200, response.text
