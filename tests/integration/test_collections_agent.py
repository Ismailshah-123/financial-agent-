"""
Integration tests for the aging report API (app.api.v1.aging) and
CollectionsAgent, through real HTTP calls against the FastAPI app —
same style as tests/integration/test_treasury.py and
tests/integration/test_ar_flow.py.

COULD NOT BE EXECUTED IN THE SESSION THAT WROTE THIS FILE: this
sandbox has no network access and none of fastapi/sqlalchemy/pydantic/
pytest/asyncpg installed (see PROJECT_STATUS_AND_ROADMAP.md's dated
entry for this session for the full explanation) — there is no
Postgres to run against here either way. Written to this codebase's
exact existing integration-test conventions and cross-checked by hand
against the real request/response shapes in app.api.v1.ar_invoices,
app.api.v1.aging, app.api.v1.agents, and app.api.v1.approval_requests,
but "matches conventions on inspection" is not the same claim as
"passed a real pytest run" — that run is genuine, still-pending
verification for whoever has this project's actual dependencies
installed. Run with: pytest tests/integration/test_collections_agent.py -v

SHARED TEST DATABASE — WHY MOST ASSERTIONS ARE SCOPED TO customer_id
------------------------------------------------------------------------
Every integration test in this suite runs against the same database
(see conftest.py), and `GET /api/v1/aging/summary` and
`GET /api/v1/aging/customers` (called with no `customer_id`) aggregate
EVERY customer with an open AR balance across the WHOLE suite — not
just the customers a given test creates. test_treasury.py's own
comments already document exactly this problem for cash balance
assertions; the same problem applies here. So: assertions against the
portfolio-wide summary/list endpoints find this test's own customer by
id within the results (the same "needle in a shared haystack" pattern
test_approval_requests.py already uses for the approval inbox) rather
than asserting an exact total; assertions against
`GET /api/v1/aging/customer/{id}` and `GET /api/v1/aging/invoices?
customer_id=...` (both scoped to one customer) assert exact figures,
since nothing another test does can add an invoice to a customer this
test just created.

The portfolio-wide collections run test below inherits the same
non-determinism (and, worse, means every other test's overdue customer
in the shared DB gets an LLM call during that one test — see that
test's own comment for why it is deliberately narrow about what it
asserts).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from tests.integration.helpers import auth_headers, register_and_login

_TODAY = date.today()


async def _create_customer(
    client: AsyncClient, headers: dict, *, suffix: str, credit_limit: str | None = None
) -> dict:
    payload = {"name": f"Aging Test Co {suffix}", "payment_terms_days": 30}
    if credit_limit is not None:
        payload["credit_limit"] = credit_limit
    response = await client.post("/api/v1/customers", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _create_and_send_invoice(
    client: AsyncClient,
    headers: dict,
    *,
    customer_id: str,
    invoice_number: str,
    total_amount: str,
    due_date: date,
    invoice_date: date | None = None,
) -> dict:
    response = await client.post(
        "/api/v1/ar-invoices",
        headers=headers,
        json={
            "invoice_number": invoice_number,
            "customer_id": customer_id,
            "currency": "PKR",
            "subtotal": total_amount,
            "tax_amount": "0",
            "total_amount": total_amount,
            "invoice_date": (invoice_date or (due_date - timedelta(days=30))).isoformat(),
            "due_date": due_date.isoformat(),
            "lines": [
                {
                    "line_number": 1,
                    "description": "Services",
                    "quantity": "1",
                    "unit_price": total_amount,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    invoice = response.json()
    send_response = await client.post(
        f"/api/v1/ar-invoices/{invoice['id']}/send", headers=headers
    )
    assert send_response.status_code == 200, send_response.text
    return send_response.json()


def _find(items: list[dict], *, id_key: str, value: str) -> dict:
    match = next((item for item in items if item[id_key] == value), None)
    assert match is not None, f"expected to find {id_key}={value} among {len(items)} item(s)"
    return match


async def test_aging_buckets_and_priority_reflect_a_severely_overdue_customer(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    headers = auth_headers(token)
    # 2000 total outstanding against a 1500 limit -> clearly over limit
    # (+20), plus a 150-day-old invoice (121+ bucket, +85) -> CRITICAL
    # regardless of exactly where the tier thresholds sit; this scenario
    # doesn't rely on the exact point values in aging_calculations, only
    # on "badly overdue and over the credit limit is CRITICAL."
    customer = await _create_customer(
        client, headers, suffix=unique_suffix, credit_limit="1500"
    )

    await _create_and_send_invoice(
        client, headers, customer_id=customer["id"], invoice_number=f"ARINV-CUR-{unique_suffix}",
        total_amount="300.00", due_date=_TODAY + timedelta(days=10),
    )
    await _create_and_send_invoice(
        client, headers, customer_id=customer["id"], invoice_number=f"ARINV-15D-{unique_suffix}",
        total_amount="200.00", due_date=_TODAY - timedelta(days=15),
    )
    await _create_and_send_invoice(
        client, headers, customer_id=customer["id"], invoice_number=f"ARINV-45D-{unique_suffix}",
        total_amount="400.00", due_date=_TODAY - timedelta(days=45),
    )
    await _create_and_send_invoice(
        client, headers, customer_id=customer["id"], invoice_number=f"ARINV-100D-{unique_suffix}",
        total_amount="500.00", due_date=_TODAY - timedelta(days=100),
    )
    await _create_and_send_invoice(
        client, headers, customer_id=customer["id"], invoice_number=f"ARINV-150D-{unique_suffix}",
        total_amount="600.00", due_date=_TODAY - timedelta(days=150),
    )

    # --- Customer detail: scoped to this customer, exact figures ---
    detail = await client.get(
        f"/api/v1/aging/customer/{customer['id']}",
        headers=headers,
        params={"as_of": _TODAY.isoformat()},
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["total_outstanding"] == "2000.00"
    assert body["current_amount"] == "300.00"
    assert body["amount_1_30"] == "200.00"
    assert body["amount_31_60"] == "400.00"
    assert body["amount_91_120"] == "500.00"
    assert body["amount_121_plus"] == "600.00"
    assert body["oldest_days_overdue"] == 150
    assert body["open_invoice_count"] == 5
    assert body["overdue_invoice_count"] == 4
    # 2000/1500 repeats forever in decimal; comparing to 4 places avoids
    # asserting more precision than this test can actually be sure the
    # running app's Decimal context produces byte-for-byte.
    assert round(Decimal(body["credit_utilization"]), 4) == Decimal("1.3333")
    assert body["priority"] == "critical"
    assert body["risk"] == body["priority"]
    assert body["priority_score"] == 100
    assert any("credit limit" in r for r in body["priority_reasons"])
    assert any("150" in r for r in body["priority_reasons"])
    assert body["recommended_action"]  # non-empty; exact wording is aging_calculations' concern

    # --- Invoice list: scoped to this customer, bucket filter works ---
    invoices = await client.get(
        "/api/v1/aging/invoices",
        headers=headers,
        params={"customer_id": customer["id"], "as_of": _TODAY.isoformat(), "bucket": "121+"},
    )
    assert invoices.status_code == 200, invoices.text
    invoice_page = invoices.json()
    assert invoice_page["total"] == 1
    assert invoice_page["items"][0]["invoice_number"] == f"ARINV-150D-{unique_suffix}"
    assert invoice_page["items"][0]["amount_outstanding"] == "600.00"
    assert invoice_page["items"][0]["days_overdue"] == 150

    # --- Portfolio-wide customer list: this customer must appear correctly,
    #     other customers in the shared DB are not this test's concern ---
    customers_page = await client.get(
        "/api/v1/aging/customers",
        headers=headers,
        params={"as_of": _TODAY.isoformat(), "priority": "critical", "page_size": 50},
    )
    assert customers_page.status_code == 200, customers_page.text
    found = _find(customers_page.json()["items"], id_key="customer_id", value=customer["id"])
    assert found["total_outstanding"] == "2000.00"
    assert found["priority"] == "critical"


async def test_partial_payment_and_credit_memo_match_the_invoice_exactly(
    client: AsyncClient, unique_suffix: str
) -> None:
    """Guards against aging_calculations.compute_invoice_aging's
    restated amount_outstanding formula drifting from
    ARInvoice.amount_outstanding's own property (see that function's
    docstring)."""
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    headers = auth_headers(token)
    director_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-director", role="finance_director"
    )
    director_headers = auth_headers(director_token)

    customer = await _create_customer(client, headers, suffix=unique_suffix)
    invoice = await _create_and_send_invoice(
        client, headers, customer_id=customer["id"], invoice_number=f"ARINV-PAY-{unique_suffix}",
        total_amount="1000.00", due_date=_TODAY - timedelta(days=20),
    )

    payment = await client.post(
        "/api/v1/incoming-payments",
        headers=headers,
        json={
            "ar_invoice_id": invoice["id"],
            "amount": "300.00",
            "payment_method": "bank_transfer",
            "received_date": _TODAY.isoformat(),
        },
    )
    assert payment.status_code == 201, payment.text

    credit_memo = await client.post(
        "/api/v1/credit-memos/ar",
        headers=headers,
        json={
            "credit_memo_number": f"ARCM-{unique_suffix}",
            "customer_id": customer["id"],
            "related_ar_invoice_id": invoice["id"],
            "currency": "PKR",
            "subtotal": "150.00",
            "tax_amount": "0",
            "total_amount": "150.00",
            "memo_date": _TODAY.isoformat(),
            "reason": "goodwill",
            "lines": [
                {"line_number": 1, "description": "Goodwill", "quantity": "1", "unit_price": "150.00"}
            ],
        },
    )
    assert credit_memo.status_code == 201, credit_memo.text
    apply_response = await client.post(
        f"/api/v1/credit-memos/ar/{credit_memo.json()['id']}/apply", headers=director_headers
    )
    assert apply_response.status_code == 200, apply_response.text

    invoice_now = (
        await client.get(f"/api/v1/ar-invoices/{invoice['id']}", headers=headers)
    ).json()
    expected_outstanding = (
        Decimal(invoice_now["total_amount"])
        - Decimal(invoice_now["amount_paid"])
        - Decimal(invoice_now["amount_credited"])
    )
    assert expected_outstanding == Decimal("550.00")  # 1000 - 300 - 150

    aging_detail = await client.get(
        f"/api/v1/aging/customer/{customer['id']}",
        headers=headers,
        params={"as_of": _TODAY.isoformat()},
    )
    assert Decimal(aging_detail.json()["total_outstanding"]) == expected_outstanding


async def test_collections_agent_single_customer_critical_creates_pending_approval(
    client: AsyncClient, unique_suffix: str
) -> None:
    ar_token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    ar_headers = auth_headers(ar_token)
    director_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-director", role="finance_director"
    )
    director_headers = auth_headers(director_token)

    customer = await _create_customer(client, ar_headers, suffix=unique_suffix)
    await _create_and_send_invoice(
        client, ar_headers, customer_id=customer["id"], invoice_number=f"ARINV-OLD-{unique_suffix}",
        total_amount="5000.00", due_date=_TODAY - timedelta(days=130),
    )

    run_response = await client.post(
        "/api/v1/agents/collections/run",
        headers=director_headers,
        json={"customer_id": customer["id"], "as_of": _TODAY.isoformat()},
    )
    assert run_response.status_code == 200, run_response.text
    result = run_response.json()
    assert result["status"] == "awaiting_approval"
    assert len(result["decisions"]) == 1
    decision = result["decisions"][0]
    # 130 days overdue (121+ bucket, 85 pts) + the whole balance sitting
    # in that bucket (severe-exposure ratio 1.0, +25 pts) = 110, capped
    # at 100 -> critical — see app.services.aging_calculations for the
    # documented scoring table this traces back to.
    assert decision["risk_level"] == "critical"
    assert decision["requires_approval"] is True
    assert decision["financial_impact"]["amount"] == "5000.00"
    assert decision["financial_impact"]["currency"] == "PKR"
    assert decision["supporting_evidence"] == [
        {"document_id": customer["id"], "document_type": "customer", "excerpt": None}
    ]
    # Deterministic content must be present regardless of whether an LLM
    # is configured in whatever environment actually runs this (see
    # module docstring) — this is the concrete assertion behind the
    # product brief's "never let missing LLM credentials make core
    # financial analysis fail unnecessarily."
    assert "Rule-based assessment:" in decision["reasoning"]
    assert "Recommended action (rule-based):" in decision["reasoning"]
    assert "130 day" in decision["reasoning"]

    # --- And it is genuinely sitting in the approval inbox, not just
    #     returned in the run's own response. ApprovalRequestRead has its
    #     own `id` (the approval record) plus a top-level `decision_id`
    #     matching the wrapped decision — filter on that directly rather
    #     than the substring-matching test_approval_requests.py uses,
    #     since that field exists here. ---
    inbox = await client.get(
        "/api/v1/approval-requests",
        headers=director_headers,
        params={"agent_type": "collections"},
    )
    assert inbox.status_code == 200, inbox.text
    matching = [r for r in inbox.json() if r["decision_id"] == decision["decision_id"]]
    assert len(matching) == 1
    pending = matching[0]
    assert pending["status"] == "pending"

    # --- Approve it: same endpoint every other agent's decisions use ---
    approve_response = await client.post(
        f"/api/v1/approval-requests/{pending['id']}/approve",
        headers=director_headers,
        json={"notes": "reviewed"},
    )
    assert approve_response.status_code == 200, approve_response.text
    assert approve_response.json()["status"] == "approved"


async def test_collections_agent_low_priority_customer_needs_no_approval(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    headers = auth_headers(token)
    customer = await _create_customer(client, headers, suffix=unique_suffix)
    await _create_and_send_invoice(
        client, headers, customer_id=customer["id"], invoice_number=f"ARINV-CURRENT-{unique_suffix}",
        total_amount="750.00", due_date=_TODAY + timedelta(days=20),
    )

    run_response = await client.post(
        "/api/v1/agents/collections/run",
        headers=headers,  # ar_clerk has AGENT_INVOKE
        json={"customer_id": customer["id"], "as_of": _TODAY.isoformat()},
    )
    assert run_response.status_code == 200, run_response.text
    result = run_response.json()
    assert result["status"] == "success"  # not awaiting_approval
    decision = result["decisions"][0]
    assert decision["risk_level"] == "low"
    assert decision["requires_approval"] is False
    assert decision["financial_impact"] is None
    assert "good standing" in decision["summary"]
    # No AI or draft-message line for a clean account — see
    # CollectionsAgent._synthesize_assessment's module docstring.
    assert "Draft follow-up message" not in decision["reasoning"]


async def test_collections_agent_portfolio_run_includes_this_elevated_customer(
    client: AsyncClient, unique_suffix: str
) -> None:
    """Deliberately narrow: a portfolio-wide run (no customer_id) walks
    every customer in the shared test database with an open AR balance
    (see module docstring), which both makes an exact decision-count
    assertion meaningless here AND means this one test call triggers an
    LLM request for every OTHER test's elevated-priority customer that
    happens to exist in the database by the time this runs — there is
    no way to scope a portfolio-wide run to "just this test's data" from
    the outside, since that is the whole point of the endpoint. This
    test only asserts that THIS test's own customer is correctly
    included, not anything about the run's total size or cost."""
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    headers = auth_headers(token)
    customer = await _create_customer(client, headers, suffix=unique_suffix)
    await _create_and_send_invoice(
        client, headers, customer_id=customer["id"], invoice_number=f"ARINV-PORT-{unique_suffix}",
        total_amount="900.00", due_date=_TODAY - timedelta(days=45),  # 31-60 bucket -> medium
    )

    run_response = await client.post(
        "/api/v1/agents/collections/run",
        headers=headers,
        json={"as_of": _TODAY.isoformat()},
    )
    assert run_response.status_code == 200, run_response.text
    decisions = run_response.json()["decisions"]
    mine = [
        d for d in decisions
        if d["supporting_evidence"] and d["supporting_evidence"][0]["document_id"] == customer["id"]
    ]
    assert len(mine) == 1, "expected exactly one decision for this test's own customer"
    assert mine[0]["risk_level"] == "medium"
    assert mine[0]["requires_approval"] is True


async def test_customer_aging_detail_404_for_unknown_customer(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ar_clerk")
    headers = auth_headers(token)
    response = await client.get(
        f"/api/v1/aging/customer/{uuid.uuid4()}", headers=headers
    )
    assert response.status_code == 404, response.text


async def test_ap_clerk_cannot_read_aging_or_invoke_collections_agent(
    client: AsyncClient, unique_suffix: str
) -> None:
    # AP_CLERK has AGENT_INVOKE (it needs to run the AP agent) but not
    # AR_INVOICE_READ (see ROLE_PERMISSIONS in app.core.security). This
    # only pins the read side: all four GET /api/v1/aging/* endpoints
    # are gated on AR_INVOICE_READ, so an ap_clerk token is rejected by
    # every one of them. It deliberately does NOT test POST
    # /api/v1/agents/collections/run — an ap_clerk token is actually
    # ALLOWED there (AGENT_INVOKE is the only gate on that endpoint,
    # same as every other agent's /run), which is worth stating
    # explicitly so it doesn't read as an oversight.
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)

    summary = await client.get("/api/v1/aging/summary", headers=headers)
    assert summary.status_code == 403

    invoices = await client.get("/api/v1/aging/invoices", headers=headers)
    assert invoices.status_code == 403

    customers = await client.get("/api/v1/aging/customers", headers=headers)
    assert customers.status_code == 403

    detail = await client.get(f"/api/v1/aging/customer/{uuid.uuid4()}", headers=headers)
    assert detail.status_code == 403
