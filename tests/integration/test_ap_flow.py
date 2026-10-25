"""
Integration tests for the full Accounts Payable flow: vendor -> purchase
order -> goods receipt -> invoice -> AI agent match -> human approval ->
payment scheduling -> payment execution. Run against a real Postgres
database and the actual FastAPI app — see tests/integration/conftest.py
for setup requirements.

NOTE ON THE AI AGENT STEP: if no LLM provider API key is configured in
the test environment (the common case for CI), `AccountsPayableAgent`'s
LLM-narrative call fails for every provider and the agent falls back to
its deterministic narrative (see `AccountsPayableAgent._get_match_narrative`
docstring) — the test still validates the full match/risk/approval
pipeline either way, since risk assessment is deterministic regardless
of whether the LLM narrative succeeded. If you configure a real
`LLM_GROQ_API_KEY` (or another provider) before running, this same test
also exercises the real LLM call path.
"""

from __future__ import annotations

from datetime import date, timedelta

from httpx import AsyncClient

from tests.integration.helpers import auth_headers, register_and_login


async def _create_vendor(client: AsyncClient, headers: dict, *, suffix: str) -> dict:
    response = await client.post(
        "/api/v1/vendors",
        headers=headers,
        json={"name": f"Acme Supplies {suffix}", "payment_terms_days": 30},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_purchase_order(
    client: AsyncClient, headers: dict, *, vendor_id: str, suffix: str
) -> dict:
    response = await client.post(
        "/api/v1/purchase-orders",
        headers=headers,
        json={
            "po_number": f"PO-{suffix}",
            "vendor_id": vendor_id,
            "currency": "USD",
            "order_date": date.today().isoformat(),
            "lines": [
                {
                    "line_number": 1,
                    "description": "Widgets",
                    "quantity_ordered": "10",
                    "unit_price": "100.00",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_full_ap_flow_happy_path(client: AsyncClient, unique_suffix: str) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)

    # --- Vendor ---
    vendor = await _create_vendor(client, headers, suffix=unique_suffix)

    # --- Purchase order ---
    po = await _create_purchase_order(client, headers, vendor_id=vendor["id"], suffix=unique_suffix)
    assert po["total_amount"] == "1000.00"
    po_line_id = po["lines"][0]["id"]

    # --- Goods receipt: fully receive the PO line ---
    grpo_response = await client.post(
        "/api/v1/goods-receipts",
        headers=headers,
        json={
            "grpo_number": f"GRPO-{unique_suffix}",
            "purchase_order_id": po["id"],
            "received_date": date.today().isoformat(),
            "lines": [{"purchase_order_line_id": po_line_id, "quantity_received": "10"}],
        },
    )
    assert grpo_response.status_code == 201, grpo_response.text

    # --- Invoice: exact match on price and quantity ---
    invoice_response = await client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "invoice_number": f"INV-{unique_suffix}",
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
    assert invoice["status"] == "received"

    # --- Run the AP agent ---
    agent_response = await client.post(
        "/api/v1/agents/accounts-payable/run",
        headers=headers,
        json={"invoice_id": invoice["id"]},
    )
    assert agent_response.status_code == 200, agent_response.text
    agent_result = agent_response.json()
    assert agent_result["status"] in ("success", "awaiting_approval")
    assert len(agent_result["decisions"]) == 1
    decision = agent_result["decisions"][0]
    assert decision["risk_level"] == "low"
    assert decision["confidence"]["value"] > 0.9

    # --- Confirm the invoice was updated to MATCHED by the agent run ---
    get_response = await client.get(f"/api/v1/invoices/{invoice['id']}", headers=headers)
    assert get_response.json()["status"] == "matched"
    assert get_response.json()["match_type"] == "three_way"

    # --- Human approves (separate actor: ap_clerk deliberately can't
    # approve its own invoice or approve/execute payments — separation
    # of duties. Mirrors test_ar_flow.py's approver pattern.) ---
    approver_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-approver", role="finance_director"
    )
    approver_headers = auth_headers(approver_token)
    approve_response = await client.post(
        f"/api/v1/invoices/{invoice['id']}/approve", headers=approver_headers
    )
    assert approve_response.status_code == 200, approve_response.text
    assert approve_response.json()["status"] == "approved"

    # --- Schedule payment (ap_clerk has payment:initiate) ---
    payment_response = await client.post(
        "/api/v1/payments",
        headers=headers,
        json={
            "invoice_id": invoice["id"],
            "payment_method": "bank_transfer",
            "scheduled_date": date.today().isoformat(),
        },
    )
    assert payment_response.status_code == 201, payment_response.text
    payment = payment_response.json()
    assert payment["status"] == "scheduled"
    assert payment["amount"] == "1000.00"

    # --- Execute payment (needs payment:approve — the approver actor) ---
    execute_response = await client.post(
        f"/api/v1/payments/{payment['id']}/execute", headers=approver_headers
    )
    assert execute_response.status_code == 200, execute_response.text
    assert execute_response.json()["status"] == "executed"
    assert execute_response.json()["bank_reference"] is not None

    # --- Invoice should now be PAID ---
    final_invoice = await client.get(f"/api/v1/invoices/{invoice['id']}", headers=headers)
    assert final_invoice.json()["status"] == "paid"


async def test_over_receipt_is_rejected(client: AsyncClient, unique_suffix: str) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)

    vendor = await _create_vendor(client, headers, suffix=unique_suffix)
    po = await _create_purchase_order(client, headers, vendor_id=vendor["id"], suffix=unique_suffix)
    po_line_id = po["lines"][0]["id"]

    # PO line ordered quantity is 10 — attempt to receive 11.
    response = await client.post(
        "/api/v1/goods-receipts",
        headers=headers,
        json={
            "grpo_number": f"GRPO-OVER-{unique_suffix}",
            "purchase_order_id": po["id"],
            "received_date": date.today().isoformat(),
            "lines": [{"purchase_order_line_id": po_line_id, "quantity_received": "11"}],
        },
    )
    assert response.status_code == 409


async def test_duplicate_invoice_is_flagged_critical_by_agent(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)

    vendor = await _create_vendor(client, headers, suffix=unique_suffix)
    invoice_number = f"DUP-INV-{unique_suffix}"

    async def _ingest_invoice() -> dict:
        response = await client.post(
            "/api/v1/invoices",
            headers=headers,
            json={
                "invoice_number": invoice_number,
                "vendor_id": vendor["id"],
                "currency": "USD",
                "subtotal": "500.00",
                "tax_amount": "0",
                "total_amount": "500.00",
                "invoice_date": date.today().isoformat(),
                "due_date": (date.today() + timedelta(days=30)).isoformat(),
                "lines": [
                    {
                        "line_number": 1,
                        "description": "Consulting services",
                        "quantity": "1",
                        "unit_price": "500.00",
                    }
                ],
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    first_invoice = await _ingest_invoice()
    second_invoice = await _ingest_invoice()  # same vendor + invoice_number

    agent_response = await client.post(
        "/api/v1/agents/accounts-payable/run",
        headers=headers,
        json={"invoice_id": second_invoice["id"]},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]
    assert decision["risk_level"] == "critical"
    assert decision["requires_approval"] is True
