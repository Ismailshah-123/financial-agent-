"""
Integration test for TaxAgent's full workflow (real DB, real HTTP,
real FastAPI dependency injection) — the DB+LLM-integrated behavior
that tests/unit/test_tax_agent.py deliberately doesn't cover (see that
file's docstring).

No LLM provider key is configured in this test environment (see
.env.example's LLM_*_API_KEY entries), so the goods/services
classification step is expected to fail and degrade to "needs manual
categorization" — see TaxAgent._classify_goods_or_services's except
clause. That degraded path is exactly what's asserted here: it proves
the whole pipeline (fetch invoice+vendor, sales-tax reasonableness
check, LLM call, graceful failure handling, AgentDecision assembly)
works end-to-end even when the LLM provider is unavailable, which is
the realistic condition for most of this test suite's runs, not an
edge case being carved out.
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient

from tests.integration.helpers import auth_headers, register_and_login

pytestmark = pytest.mark.asyncio


async def _create_vendor(client: AsyncClient, headers: dict[str, str], *, suffix: str) -> dict:
    response = await client.post(
        "/api/v1/vendors",
        headers=headers,
        json={
            "name": f"Tax Test Supplies {suffix}",
            "default_currency": "PKR",
            "payment_terms_days": 30,
            "filer_status": "filer",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_tax_agent_flags_consistent_gst_and_needs_categorization(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)

    vendor = await _create_vendor(client, headers, suffix=unique_suffix)

    invoice_response = await client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "vendor_id": vendor["id"],
            "invoice_number": f"TAX-INV-{unique_suffix}",
            "currency": "PKR",
            "invoice_date": date.today().isoformat(),
            "due_date": date.today().isoformat(),
            "subtotal": "10000.00",
            "total_amount": "10000.00",  # ignored/recomputed since tax_code is set
            "tax_code": "PK-GST-STD",
            "lines": [
                {
                    "line_number": 1,
                    "description": "Consulting services — Q3 engagement",
                    "quantity": "1",
                    "unit_price": "10000.00",
                }
            ],
        },
    )
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()
    assert invoice["tax_amount"] == "1800.00"  # 18% GST on 10000 — sanity check

    agent_response = await client.post(
        "/api/v1/agents/tax/run",
        headers=headers,
        json={"invoice_id": invoice["id"]},
    )
    assert agent_response.status_code == 200, agent_response.text
    result = agent_response.json()

    assert result["status"] in ("awaiting_approval", "success")
    decision = result["decisions"][0]

    # Sales tax: 1800 on 10000 is exactly the seeded 18% GST rate, so
    # this must NOT be flagged as an anomaly.
    assert "does not match" not in decision["reasoning"]
    assert "PK-GST-STD" in decision["reasoning"]

    # No LLM key configured in this environment -> classification
    # degrades to "needs manual categorization", never a guess.
    assert decision["risk_level"] == "medium"
    assert decision["requires_approval"] is True
    assert "manual categorization" in decision["reasoning"].lower()
    assert decision["financial_impact"] is None


async def test_tax_agent_flags_sales_tax_anomaly(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)
    vendor = await _create_vendor(client, headers, suffix=unique_suffix)

    # No tax_code supplied — tax_amount is a flat client-supplied value
    # that doesn't correspond to any active rate (23% matches nothing).
    invoice_response = await client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "vendor_id": vendor["id"],
            "invoice_number": f"TAX-ANOMALY-{unique_suffix}",
            "currency": "PKR",
            "invoice_date": date.today().isoformat(),
            "due_date": date.today().isoformat(),
            "subtotal": "10000.00",
            "total_amount": "12300.00",
            "tax_amount": "2300.00",
            "lines": [
                {
                    "line_number": 1,
                    "description": "Office supplies",
                    "quantity": "1",
                    "unit_price": "10000.00",
                }
            ],
        },
    )
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()

    agent_response = await client.post(
        "/api/v1/agents/tax/run",
        headers=headers,
        json={"invoice_id": invoice["id"]},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    assert decision["risk_level"] == "high"
    assert decision["requires_approval"] is True
    assert "does not match" in decision["reasoning"]
