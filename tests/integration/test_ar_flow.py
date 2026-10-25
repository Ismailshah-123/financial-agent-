"""
Integration tests for the Accounts Receivable flow: customer -> AR
invoice -> send (revenue recognized) -> AR agent risk assessment -> AR
credit memo issuance and application. Run against a real Postgres
database and the actual FastAPI app — see tests/integration/conftest.py
for setup requirements. Same LLM-fallback note as test_ap_flow.py
applies here: without a configured LLM provider key, the AR agent falls
back to its deterministic narrative, and the risk-assessment pipeline
is validated either way.
"""

from __future__ import annotations

from datetime import date, timedelta

from httpx import AsyncClient

from tests.integration.helpers import auth_headers, register_and_login


async def _create_customer(
    client: AsyncClient, headers: dict, *, suffix: str, credit_limit: str | None = None
) -> dict:
    payload = {"name": f"Globex Corp {suffix}", "payment_terms_days": 30}
    if credit_limit is not None:
        payload["credit_limit"] = credit_limit
    response = await client.post("/api/v1/customers", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_full_ar_flow_happy_path(client: AsyncClient, unique_suffix: str) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    headers = auth_headers(token)

    customer = await _create_customer(client, headers, suffix=unique_suffix, credit_limit="10000")

    # --- Ingest AR invoice (DRAFT) ---
    invoice_response = await client.post(
        "/api/v1/ar-invoices",
        headers=headers,
        json={
            "invoice_number": f"ARINV-{unique_suffix}",
            "customer_id": customer["id"],
            "currency": "USD",
            "subtotal": "1000.00",
            "tax_amount": "0",
            "total_amount": "1000.00",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "lines": [
                {
                    "line_number": 1,
                    "description": "Consulting services",
                    "quantity": "1",
                    "unit_price": "1000.00",
                }
            ],
        },
    )
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()
    assert invoice["status"] == "draft"

    # --- Send it (revenue recognized) ---
    send_response = await client.post(
        f"/api/v1/ar-invoices/{invoice['id']}/send", headers=headers
    )
    assert send_response.status_code == 200, send_response.text
    assert send_response.json()["status"] == "sent"

    # --- Run the AR agent — not overdue, well under credit limit -> LOW risk ---
    agent_response = await client.post(
        "/api/v1/agents/accounts-receivable/run",
        headers=headers,
        json={"ar_invoice_id": invoice["id"]},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]
    assert decision["risk_level"] == "low"

    # --- Issue an AR credit memo against the invoice ---
    credit_memo_response = await client.post(
        "/api/v1/credit-memos/ar",
        headers=headers,
        json={
            "credit_memo_number": f"ARCM-{unique_suffix}",
            "customer_id": customer["id"],
            "related_ar_invoice_id": invoice["id"],
            "currency": "USD",
            "subtotal": "200.00",
            "tax_amount": "0",
            "total_amount": "200.00",
            "memo_date": date.today().isoformat(),
            "reason": "goodwill",
            "lines": [
                {
                    "line_number": 1,
                    "description": "Goodwill discount",
                    "quantity": "1",
                    "unit_price": "200.00",
                }
            ],
        },
    )
    assert credit_memo_response.status_code == 201, credit_memo_response.text
    credit_memo = credit_memo_response.json()
    assert credit_memo["status"] == "draft"

    # --- Apply it (requires CREDIT_MEMO_APPROVE — finance_director has it) ---
    approver_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-approver", role="finance_director"
    )
    apply_response = await client.post(
        f"/api/v1/credit-memos/ar/{credit_memo['id']}/apply",
        headers=auth_headers(approver_token),
    )
    assert apply_response.status_code == 200, apply_response.text
    assert apply_response.json()["status"] == "applied"

    # --- Invoice's outstanding balance should now be reduced by the credit ---
    final_invoice = await client.get(f"/api/v1/ar-invoices/{invoice['id']}", headers=headers)
    assert final_invoice.json()["amount_credited"] == "200.00"
    assert final_invoice.json()["amount_paid"] == "0.00"


async def test_over_credit_limit_triggers_high_risk(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    headers = auth_headers(token)

    # Small credit limit, large invoice — guarantees over-limit.
    customer = await _create_customer(client, headers, suffix=unique_suffix, credit_limit="100")

    invoice_response = await client.post(
        "/api/v1/ar-invoices",
        headers=headers,
        json={
            "invoice_number": f"ARINV-OVER-{unique_suffix}",
            "customer_id": customer["id"],
            "currency": "USD",
            "subtotal": "5000.00",
            "tax_amount": "0",
            "total_amount": "5000.00",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "lines": [
                {
                    "line_number": 1,
                    "description": "Large order",
                    "quantity": "1",
                    "unit_price": "5000.00",
                }
            ],
        },
    )
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()

    await client.post(f"/api/v1/ar-invoices/{invoice['id']}/send", headers=headers)

    agent_response = await client.post(
        "/api/v1/agents/accounts-receivable/run",
        headers=headers,
        json={"ar_invoice_id": invoice["id"]},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]
    assert decision["risk_level"] in ("high", "critical")
    assert decision["requires_approval"] is True


async def test_credit_memo_exceeding_outstanding_balance_is_rejected(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    headers = auth_headers(token)

    customer = await _create_customer(client, headers, suffix=unique_suffix)

    invoice_response = await client.post(
        "/api/v1/ar-invoices",
        headers=headers,
        json={
            "invoice_number": f"ARINV-SMALL-{unique_suffix}",
            "customer_id": customer["id"],
            "currency": "USD",
            "subtotal": "100.00",
            "tax_amount": "0",
            "total_amount": "100.00",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "lines": [
                {"line_number": 1, "description": "Small order", "quantity": "1", "unit_price": "100.00"}
            ],
        },
    )
    invoice = invoice_response.json()
    await client.post(f"/api/v1/ar-invoices/{invoice['id']}/send", headers=headers)

    # Credit memo for MORE than the invoice total.
    response = await client.post(
        "/api/v1/credit-memos/ar",
        headers=headers,
        json={
            "credit_memo_number": f"ARCM-OVER-{unique_suffix}",
            "customer_id": customer["id"],
            "related_ar_invoice_id": invoice["id"],
            "currency": "USD",
            "subtotal": "500.00",
            "tax_amount": "0",
            "total_amount": "500.00",
            "memo_date": date.today().isoformat(),
            "lines": [
                {"line_number": 1, "description": "Oversized credit", "quantity": "1", "unit_price": "500.00"}
            ],
        },
    )
    assert response.status_code == 409


async def test_partial_incoming_payments_move_invoice_through_statuses(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    headers = auth_headers(token)

    customer = await _create_customer(client, headers, suffix=unique_suffix)

    invoice_response = await client.post(
        "/api/v1/ar-invoices",
        headers=headers,
        json={
            "invoice_number": f"ARINV-PARTIAL-{unique_suffix}",
            "customer_id": customer["id"],
            "currency": "USD",
            "subtotal": "1000.00",
            "tax_amount": "0",
            "total_amount": "1000.00",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "lines": [
                {"line_number": 1, "description": "Services", "quantity": "1", "unit_price": "1000.00"}
            ],
        },
    )
    invoice = invoice_response.json()
    await client.post(f"/api/v1/ar-invoices/{invoice['id']}/send", headers=headers)

    # --- First partial payment ---
    first_payment = await client.post(
        "/api/v1/incoming-payments",
        headers=headers,
        json={
            "ar_invoice_id": invoice["id"],
            "amount": "400.00",
            "payment_method": "bank_transfer",
            "received_date": date.today().isoformat(),
        },
    )
    assert first_payment.status_code == 201, first_payment.text
    assert first_payment.json()["status"] == "executed"

    mid_invoice = await client.get(f"/api/v1/ar-invoices/{invoice['id']}", headers=headers)
    assert mid_invoice.json()["status"] == "partially_paid"
    assert mid_invoice.json()["amount_paid"] == "400.00"

    # --- Overpayment attempt is rejected ---
    overpay = await client.post(
        "/api/v1/incoming-payments",
        headers=headers,
        json={
            "ar_invoice_id": invoice["id"],
            "amount": "1000.00",  # only 600 remaining
            "payment_method": "bank_transfer",
            "received_date": date.today().isoformat(),
        },
    )
    assert overpay.status_code == 422

    # --- Second payment completes it ---
    second_payment = await client.post(
        "/api/v1/incoming-payments",
        headers=headers,
        json={
            "ar_invoice_id": invoice["id"],
            "amount": "600.00",
            "payment_method": "bank_transfer",
            "received_date": date.today().isoformat(),
        },
    )
    assert second_payment.status_code == 201, second_payment.text

    final_invoice = await client.get(f"/api/v1/ar-invoices/{invoice['id']}", headers=headers)
    assert final_invoice.json()["status"] == "paid"
    assert final_invoice.json()["amount_paid"] == "1000.00"
