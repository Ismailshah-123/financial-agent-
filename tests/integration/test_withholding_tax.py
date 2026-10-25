"""
Integration test for withholding tax applied at payment time: create a
vendor with filer_status, an invoice with tax_code-driven GST, approve
it, then schedule and execute a payment WITH a withholding_tax_code —
proves the net amount transferred, the withheld amount recorded, and
the resulting journal entry all reconcile correctly against a real
database. See tests/integration/conftest.py for setup requirements.
"""

from __future__ import annotations

from datetime import date, timedelta

from httpx import AsyncClient

from tests.integration.helpers import auth_headers, register_and_login


async def test_full_ap_flow_with_gst_and_withholding_tax(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)

    vendor_response = await client.post(
        "/api/v1/vendors",
        headers=headers,
        json={
            "name": f"WHT Test Vendor {unique_suffix}",
            "payment_terms_days": 30,
            "default_currency": "PKR",
            "filer_status": "filer",
        },
    )
    assert vendor_response.status_code == 201, vendor_response.text
    vendor = vendor_response.json()
    assert vendor["filer_status"] == "filer"

    invoice_response = await client.post(
        "/api/v1/invoices",
        headers=headers,
        json={
            "invoice_number": f"INV-WHT-{unique_suffix}",
            "vendor_id": vendor["id"],
            "currency": "PKR",
            "subtotal": "10000.00",
            "total_amount": "10000.00",  # ignored/recomputed since tax_code is set
            "tax_code": "PK-GST-STD",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "lines": [
                {
                    "line_number": 1,
                    "description": "Consulting services",
                    "quantity": "1",
                    "unit_price": "10000.00",
                }
            ],
        },
    )
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()
    assert invoice["tax_amount"] == "1800.00"
    assert invoice["total_amount"] == "11800.00"

    approver_token = await register_and_login(
        client, unique_suffix=f"{unique_suffix}-approver", role="finance_director"
    )
    approver_headers = auth_headers(approver_token)

    approve_response = await client.post(
        f"/api/v1/invoices/{invoice['id']}/approve", headers=approver_headers
    )
    assert approve_response.status_code == 200, approve_response.text

    payment_response = await client.post(
        "/api/v1/payments",
        headers=headers,
        json={
            "invoice_id": invoice["id"],
            "payment_method": "bank_transfer",
            "scheduled_date": date.today().isoformat(),
            "withholding_tax_code": "PK-WHT-153-GOODS-FILER",
        },
    )
    assert payment_response.status_code == 201, payment_response.text
    payment = payment_response.json()
    assert payment["withholding_tax_code"] == "PK-WHT-153-GOODS-FILER"
    assert payment["withholding_tax_amount"] == "472.00"
    # Net transferred = invoice total (11800) - withheld (472) = 11328.00
    assert payment["amount"] == "11328.00"

    execute_response = await client.post(
        f"/api/v1/payments/{payment['id']}/execute", headers=approver_headers
    )
    assert execute_response.status_code == 200, execute_response.text
    assert execute_response.json()["status"] == "executed"

    final_invoice = await client.get(f"/api/v1/invoices/{invoice['id']}", headers=headers)
    assert final_invoice.json()["status"] == "paid"

    trial_balance_response = await client.get(
        "/api/v1/reports/trial-balance",
        headers=approver_headers,
        params={"as_of": date.today().isoformat()},
    )
    assert trial_balance_response.status_code == 200, trial_balance_response.text
    accounts_by_code = {
        line["account_code"]: line for line in trial_balance_response.json()["lines"]
    }
    assert "2100-WHT" in accounts_by_code
    assert float(accounts_by_code["2100-WHT"]["total_credit"]) >= 472.00
