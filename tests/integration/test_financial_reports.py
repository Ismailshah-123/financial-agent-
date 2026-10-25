"""
Integration tests for app.api.v1.reports — proves the Trial Balance and
P&L actually reflect real posted journal entries, not just that the
calculation code is right in isolation (that's what
tests/unit/test_financial_reporting_service.py covers). Runs the real
AP flow (vendor -> PO -> invoice -> approve, which posts a journal
entry via PostingService) then checks the reports reflect it. See
tests/integration/conftest.py for setup requirements.
"""

from __future__ import annotations

from datetime import date, timedelta

from httpx import AsyncClient

from tests.integration.helpers import auth_headers, register_and_login


async def test_trial_balance_reflects_posted_ap_invoice_approval(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)

    vendor_response = await client.post(
        "/api/v1/vendors",
        headers=headers,
        json={"name": f"Report Test Vendor {unique_suffix}", "payment_terms_days": 30},
    )
    vendor = vendor_response.json()

    po_response = await client.post(
        "/api/v1/purchase-orders",
        headers=headers,
        json={
            "po_number": f"PO-RPT-{unique_suffix}",
            "vendor_id": vendor["id"],
            "currency": "USD",
            "order_date": date.today().isoformat(),
            "lines": [
                {
                    "line_number": 1,
                    "description": "Reporting test line",
                    "quantity_ordered": "1",
                    "unit_price": "750.00",
                }
            ],
        },
    )
    po = po_response.json()
    po_line_id = po["lines"][0]["id"]

    await client.post(
        "/api/v1/goods-receipts",
        headers=headers,
        json={
            "grpo_number": f"GRPO-RPT-{unique_suffix}",
            "purchase_order_id": po["id"],
            "received_date": date.today().isoformat(),
            "lines": [{"purchase_order_line_id": po_line_id, "quantity_received": "1"}],
        },
    )

    invoice_response = await client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "invoice_number": f"INV-RPT-{unique_suffix}",
            "vendor_id": vendor["id"],
            "purchase_order_id": po["id"],
            "currency": "USD",
            "subtotal": "750.00",
            "tax_amount": "0",
            "total_amount": "750.00",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "lines": [
                {
                    "line_number": 1,
                    "purchase_order_line_id": po_line_id,
                    "description": "Reporting test line",
                    "quantity": "1",
                    "unit_price": "750.00",
                }
            ],
        },
    )
    invoice = invoice_response.json()

    approver_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-approver", role="finance_director"
    )
    approve_response = await client.post(
        f"/api/v1/invoices/{invoice['id']}/approve", headers=auth_headers(approver_token)
    )
    assert approve_response.status_code == 200, approve_response.text

    trial_balance_response = await client.get(
        "/api/v1/reports/trial-balance",
        headers=auth_headers(approver_token),
        params={"as_of": date.today().isoformat(), "currency": "USD"},
    )
    assert trial_balance_response.status_code == 200, trial_balance_response.text
    trial_balance = trial_balance_response.json()
    assert trial_balance["is_balanced"] is True

    accounts_by_code = {line["account_code"]: line for line in trial_balance["lines"]}
    assert "5000-EXP" in accounts_by_code
    assert "2000-AP" in accounts_by_code
    assert float(accounts_by_code["5000-EXP"]["total_debit"]) >= 750.00
    assert float(accounts_by_code["2000-AP"]["total_credit"]) >= 750.00


async def test_profit_and_loss_reflects_posted_expense(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)

    vendor_response = await client.post(
        "/api/v1/vendors",
        headers=headers,
        json={"name": f"PnL Test Vendor {unique_suffix}", "payment_terms_days": 30},
    )
    vendor = vendor_response.json()

    invoice_response = await client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "invoice_number": f"INV-PNL-{unique_suffix}",
            "vendor_id": vendor["id"],
            "currency": "USD",
            "subtotal": "300.00",
            "tax_amount": "0",
            "total_amount": "300.00",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "lines": [
                {
                    "line_number": 1,
                    "description": "PnL test line",
                    "quantity": "1",
                    "unit_price": "300.00",
                }
            ],
        },
    )
    invoice = invoice_response.json()
    approver_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-approver", role="finance_director"
    )
    await client.post(
        f"/api/v1/invoices/{invoice['id']}/approve", headers=auth_headers(approver_token)
    )

    pnl_response = await client.get(
        "/api/v1/reports/profit-and-loss",
        headers=auth_headers(approver_token),
        params={
            "start_date": date.today().isoformat(),
            "end_date": date.today().isoformat(),
            "currency": "USD",
        },
    )
    assert pnl_response.status_code == 200, pnl_response.text
    pnl = pnl_response.json()
    expense_codes = {line["account_code"] for line in pnl["expense_lines"]}
    assert "5000-EXP" in expense_codes
    assert float(pnl["total_expense"]) >= 300.00


async def test_balance_sheet_generates_successfully_with_seeded_chart_of_accounts(
    client: AsyncClient, unique_suffix: str
) -> None:
    """Sanity check on the reporting invariant itself: every account
    seeded by 0004_chart_of_accounts.py must exist, so a normal AP flow
    should never hit FinancialReportingService's "unmapped account"
    error. This confirms reports succeed at all when the chart of
    accounts is correctly seeded — the precondition every other report
    test here relies on."""
    token = await register_and_login(client, unique_suffix=unique_suffix)
    headers = auth_headers(token)

    response = await client.get(
        "/api/v1/reports/balance-sheet",
        headers=headers,
        params={"as_of": date.today().isoformat(), "currency": "USD"},
    )
    assert response.status_code == 200, response.text


async def _post_approved_invoice(
    client: AsyncClient, *, unique_suffix: str, currency: str, amount: str, label: str
) -> None:
    """Create a vendor and an invoice in `currency`, then approve it so a
    journal entry in that currency is posted to the ledger."""
    token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-{label}-clerk", role="ap_clerk"
    )
    headers = auth_headers(token)
    vendor = (
        await client.post(
            "/api/v1/vendors",
            headers=headers,
            json={
                "name": f"{label} Vendor {unique_suffix}",
                "payment_terms_days": 30,
                "default_currency": currency,
            },
        )
    ).json()
    invoice = (
        await client.post(
            "/api/v1/invoices",
            headers=headers,
            json={
                "invoice_number": f"INV-{label}-{unique_suffix}",
                "vendor_id": vendor["id"],
                "currency": currency,
                "subtotal": amount,
                "tax_amount": "0",
                "total_amount": amount,
                "invoice_date": date.today().isoformat(),
                "due_date": (date.today() + timedelta(days=30)).isoformat(),
                "lines": [
                    {
                        "line_number": 1,
                        "description": f"{label} line",
                        "quantity": "1",
                        "unit_price": amount,
                    }
                ],
            },
        )
    ).json()
    approver = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-{label}-approver", role="finance_director"
    )
    approved = await client.post(
        f"/api/v1/invoices/{invoice['id']}/approve", headers=auth_headers(approver)
    )
    assert approved.status_code == 200, approved.text


async def test_reports_never_combine_currencies(
    client: AsyncClient, unique_suffix: str
) -> None:
    """Regression: the General Ledger reports used to SUM journal lines across
    every currency. With postings in two currencies the report must either be
    produced for one explicit currency or be refused."""
    await _post_approved_invoice(
        client, unique_suffix=unique_suffix, currency="USD", amount="410.00", label="USDX"
    )
    await _post_approved_invoice(
        client, unique_suffix=unique_suffix, currency="EUR", amount="205.00", label="EURX"
    )
    viewer = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-viewer", role="finance_director"
    )
    headers = auth_headers(viewer)
    today = date.today().isoformat()

    currencies = await client.get("/api/v1/reports/currencies", headers=headers)
    assert currencies.status_code == 200, currencies.text
    assert {"USD", "EUR"} <= set(currencies.json()["currencies"])

    # Ambiguous request: refused, with the choices listed, never silently summed.
    ambiguous = await client.get(
        "/api/v1/reports/trial-balance", headers=headers, params={"as_of": today}
    )
    assert ambiguous.status_code == 422, ambiguous.text
    assert {"USD", "EUR"} <= set(ambiguous.json()["details"]["available_currencies"])

    # Each explicit currency is internally balanced and labelled with its own code.
    for code in ("USD", "EUR"):
        report = await client.get(
            "/api/v1/reports/trial-balance",
            headers=headers,
            params={"as_of": today, "currency": code},
        )
        assert report.status_code == 200, report.text
        body = report.json()
        assert body["currency"] == code
        assert body["is_balanced"] is True
        assert code in body["available_currencies"]

    eur_pnl = await client.get(
        "/api/v1/reports/profit-and-loss",
        headers=headers,
        params={"start_date": today, "end_date": today, "currency": "EUR"},
    )
    assert eur_pnl.status_code == 200, eur_pnl.text
    assert eur_pnl.json()["currency"] == "EUR"
    assert float(eur_pnl.json()["total_expense"]) >= 205.00

    malformed = await client.get(
        "/api/v1/reports/balance-sheet",
        headers=headers,
        params={"as_of": today, "currency": "EURO"},
    )
    assert malformed.status_code == 422, malformed.text
