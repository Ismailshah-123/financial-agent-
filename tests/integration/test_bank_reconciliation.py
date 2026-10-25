"""
Integration tests for bank reconciliation: ingest -> agent recommends
-> confirm match, against real Postgres and the real API.

DATE NOTE: unlike test_period_close.py, these tests use today's date
throughout (the same date every AR/AP flow test in this suite uses)
rather than backdating — reconciliation doesn't interact with the
period-lock, so there's no isolation reason to avoid it here, and using
`send_invoice`/`create_incoming_payment` through the real API (both of
which hardcode posting_date=today, per app.services.ar_invoice_service)
is simpler and more representative than posting directly.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.integration.helpers import auth_headers, register_and_login

pytestmark = pytest.mark.asyncio


async def _create_customer_with_paid_invoice(
    client: AsyncClient, headers: dict, *, suffix: str, bank_reference: str
) -> dict:
    """Returns the created IncomingPayment — customer -> AR invoice ->
    send -> record incoming payment, all as one ar_clerk actor."""
    customer_response = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": f"Bank Recon Test Customer {suffix}", "payment_terms_days": 30},
    )
    assert customer_response.status_code == 201, customer_response.text
    customer = customer_response.json()

    invoice_response = await client.post(
        "/api/v1/ar-invoices",
        headers=headers,
        json={
            "invoice_number": f"ARINV-BR-{suffix}",
            "customer_id": customer["id"],
            "currency": "PKR",
            "subtotal": "3000.00",
            "tax_amount": "0",
            "total_amount": "3000.00",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "lines": [
                {"line_number": 1, "description": "Services rendered", "quantity": "1", "unit_price": "3000.00"}
            ],
        },
    )
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()

    send_response = await client.post(f"/api/v1/ar-invoices/{invoice['id']}/send", headers=headers)
    assert send_response.status_code == 200, send_response.text

    payment_response = await client.post(
        "/api/v1/incoming-payments",
        headers=headers,
        json={
            "ar_invoice_id": invoice["id"],
            "amount": "3000.00",
            "payment_method": "bank_transfer",
            "received_date": date.today().isoformat(),
            "bank_reference": bank_reference,
        },
    )
    assert payment_response.status_code == 201, payment_response.text
    return payment_response.json()


async def test_reference_match_recommends_low_risk_confirm(
    client: AsyncClient, unique_suffix: str
) -> None:
    ar_token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    ar_headers = auth_headers(ar_token)
    bank_reference = f"BR-REF-{unique_suffix}"
    payment = await _create_customer_with_paid_invoice(
        client, ar_headers, suffix=unique_suffix, bank_reference=bank_reference
    )

    director_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-director", role="finance_director"
    )
    director_headers = auth_headers(director_token)

    ingest_response = await client.post(
        "/api/v1/bank-reconciliation/statement-lines",
        headers=director_headers,
        json={
            "statement_label": f"Test Bank {unique_suffix}",
            "lines": [
                {
                    "transaction_date": date.today().isoformat(),
                    "description": "Incoming wire",
                    "amount": "3000.00",
                    "currency": "PKR",
                    "bank_reference": bank_reference,
                }
            ],
        },
    )
    assert ingest_response.status_code == 201, ingest_response.text
    statement_line = ingest_response.json()[0]
    assert statement_line["is_matched"] is False

    agent_response = await client.post(
        "/api/v1/agents/bank-reconciliation/run",
        headers=director_headers,
        json={"statement_line_id": statement_line["id"]},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]
    assert decision["risk_level"] == "low"
    assert decision["confidence"]["value"] == 0.9
    assert payment["id"] in decision["reasoning"] or payment["id"] in str(decision["supporting_evidence"])

    confirm_response = await client.post(
        f"/api/v1/bank-reconciliation/statement-lines/{statement_line['id']}/confirm-match",
        headers=director_headers,
        json={"payment_type": "incoming", "payment_id": payment["id"]},
    )
    assert confirm_response.status_code == 200, confirm_response.text
    confirmed = confirm_response.json()
    assert confirmed["is_matched"] is True
    assert confirmed["matched_payment_id"] == payment["id"]

    # Confirming twice is rejected.
    second_confirm = await client.post(
        f"/api/v1/bank-reconciliation/statement-lines/{statement_line['id']}/confirm-match",
        headers=director_headers,
        json={"payment_type": "incoming", "payment_id": payment["id"]},
    )
    assert second_confirm.status_code == 409


async def test_no_candidates_recommends_journal_entry_with_financial_impact(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)

    ingest_response = await client.post(
        "/api/v1/bank-reconciliation/statement-lines",
        headers=headers,
        json={
            "statement_label": f"Test Bank {unique_suffix}",
            "lines": [
                {
                    "transaction_date": date.today().isoformat(),
                    "description": "MONTHLY ACCOUNT MAINTENANCE FEE",
                    "amount": "-35.00",
                    "currency": "PKR",
                }
            ],
        },
    )
    assert ingest_response.status_code == 201, ingest_response.text
    statement_line = ingest_response.json()[0]

    agent_response = await client.post(
        "/api/v1/agents/bank-reconciliation/run",
        headers=headers,
        json={"statement_line_id": statement_line["id"]},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    # No LLM key configured in this sandbox -> classification degrades
    # to "unknown"/0.0 confidence -> HIGH risk (see agent's risk rule).
    assert decision["risk_level"] == "high"
    assert decision["requires_approval"] is True
    assert decision["financial_impact"] is not None
    assert decision["financial_impact"]["amount"] == "35.00"


async def test_ap_clerk_cannot_ingest_statement_lines(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="viewer")
    headers = auth_headers(token)
    response = await client.post(
        "/api/v1/bank-reconciliation/statement-lines",
        headers=headers,
        json={
            "statement_label": "x",
            "lines": [
                {
                    "transaction_date": date.today().isoformat(),
                    "description": "x",
                    "amount": "1.00",
                    "currency": "PKR",
                }
            ],
        },
    )
    assert response.status_code == 403
