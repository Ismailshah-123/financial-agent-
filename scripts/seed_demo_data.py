#!/usr/bin/env python3
"""
scripts/seed_demo_data.py
==========================
Loads FAKE demo data into a LOCAL copy of the platform so every screen has something to show:
vendors, purchase orders, goods receipts, AP invoices (clean, price-mismatch, short-received,
duplicate, overdue), customers, AR invoices across every aging bucket, incoming payments,
bank statement lines and budgets. Nothing here is real and no SAP connection is needed.

Usage (backend must be running in another terminal: `uvicorn app.main:app --reload`):

    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --skip-agents     # faster: do not run the AI agents

What it does, in order:
  1. Creates three demo users directly in the database (a platform rule is that the people who
     enter documents are not the people who approve them, so one account cannot do everything):
         demo.ap@example.com        ap_clerk          enters vendors, POs, invoices, payments
         demo.ar@example.com        ar_clerk          enters customers, AR invoices, receipts
         demo.director@example.com  finance_director  approves invoices, executes payments
  2. Drives the real HTTP API as those users, exactly like the frontend would.

Safe by design: refuses to run unless APP_ENVIRONMENT is local, development or test, and refuses
to run twice (it detects its own vendors). Each step is independent: a failed step is reported
and the script carries on, so you always see a full summary at the end.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API = os.environ.get("SEED_API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
DEMO_PASSWORD = "DemoPassw0rd!2026"
DEMO_USERS = {
    "ap": ("demo.ap@example.com", "Demo AP Clerk", "ap_clerk"),
    "ar": ("demo.ar@example.com", "Demo AR Clerk", "ar_clerk"),
    "director": ("demo.director@example.com", "Demo Finance Director", "finance_director"),
}
TODAY = date.today()


def d(offset_days: int) -> str:
    return (TODAY + timedelta(days=offset_days)).isoformat()


# ----------------------------------------------------------------------------- reporting
class Report:
    def __init__(self) -> None:
        self.ok = 0
        self.failed: list[str] = []

    def good(self, label: str) -> None:
        self.ok += 1
        print(f"  ok    {label}")

    def bad(self, label: str, detail: str) -> None:
        self.failed.append(f"{label}: {detail}")
        print(f"  FAIL  {label}\n        {detail[:300]}")


REPORT = Report()


class Api:
    """Thin authenticated wrapper. `call` returns parsed JSON or None (and records the failure)."""

    def __init__(self, role: str, client: httpx.Client) -> None:
        self.role = role
        self.client = client
        self.headers: dict[str, str] = {}

    def login(self) -> bool:
        email = DEMO_USERS[self.role][0]
        response = self.client.post(f"{API}/auth/login", json={"email": email, "password": DEMO_PASSWORD})
        if response.status_code != 200:
            REPORT.bad(f"login {email}", f"{response.status_code} {response.text}")
            return False
        self.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        return True

    def call(self, label: str, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.client.request(method, f"{API}{path}", headers=self.headers, **kwargs)
        except httpx.HTTPError as exc:
            REPORT.bad(label, f"{type(exc).__name__}: {exc}")
            return None
        if response.status_code >= 400:
            REPORT.bad(label, f"{response.status_code} {response.text}")
            return None
        REPORT.good(label)
        return response.json() if response.content else {}


# ----------------------------------------------------------------------------- users (DB)
async def ensure_users() -> bool:
    from app.core.config import settings
    from app.core.constants import UserRole
    from app.core.exceptions import ConflictError
    from app.db.session import engine, session_scope
    from app.schemas.user import UserCreate
    from app.services.auth_service import AuthService

    environment = settings.app.environment.value
    if environment not in {"local", "development", "test"}:
        print(f"Refusing to seed demo data into a '{environment}' environment.")
        return False
    try:
        for email, full_name, role in DEMO_USERS.values():
            try:
                async with session_scope() as session:
                    await AuthService(session).register(
                        UserCreate(email=email, password=DEMO_PASSWORD, full_name=full_name, role=UserRole(role))
                    )
                print(f"  ok    created demo user {email} ({role})")
            except ConflictError:
                print(f"  ok    demo user {email} already exists")
    finally:
        await engine.dispose()
    return True


# ----------------------------------------------------------------------------- AP scenarios
def vendor_payload(name: str, terms: int, currency: str, tax_id: str) -> dict[str, Any]:
    slug = name.split(" (")[0].lower().replace(" ", "-")
    return {
        "name": name,
        "tax_id": tax_id,
        "email": f"accounts@{slug}.example.com",
        "phone": "+92-21-5550100",
        "address_line": "Demo Industrial Area, Karachi",
        "default_currency": currency,
        "payment_terms_days": terms,
    }


def seed_ap(ap: Api, director: Api, run_agents: bool) -> None:
    print("\nAccounts payable")
    specs = [
        ("Indus Office Supplies (Demo)", 30, "PKR", "DEMO-NTN-1001"),
        ("Crescent IT Solutions (Demo)", 45, "PKR", "DEMO-NTN-1002"),
        ("Karachi Packaging Co (Demo)", 30, "PKR", "DEMO-NTN-1003"),
        ("Sindh Logistics Pvt Ltd (Demo)", 15, "PKR", "DEMO-NTN-1004"),
        ("Gulf Stationers FZE (Demo)", 30, "USD", "DEMO-TRN-2001"),
    ]
    vendors: dict[str, dict[str, Any]] = {}
    for name, terms, currency, tax_id in specs:
        vendor = ap.call(f"vendor {name}", "POST", "/vendors", json=vendor_payload(name, terms, currency, tax_id))
        if vendor:
            vendors[name] = vendor
            director.call(f"activate {name}", "POST", f"/vendors/{vendor['id']}/activate")

    def run_agent(invoice: dict[str, Any], label: str) -> None:
        if run_agents:
            ap.call(f"AP agent on {label}", "POST", "/agents/accounts-payable/run", json={"invoice_id": invoice["id"]})

    def make_po(po_no: str, vendor: dict[str, Any], currency: str, qty: str, price: str, desc: str) -> dict[str, Any] | None:
        return ap.call(
            f"PO {po_no}", "POST", "/purchase-orders",
            json={
                "po_number": po_no, "vendor_id": vendor["id"], "currency": currency, "order_date": d(-40),
                "lines": [{"line_number": 1, "description": desc, "quantity_ordered": qty, "unit_price": price}],
            },
        )

    def receive(grpo_no: str, po: dict[str, Any], qty: str) -> None:
        ap.call(
            f"goods receipt {grpo_no}", "POST", "/goods-receipts",
            json={
                "grpo_number": grpo_no, "purchase_order_id": po["id"], "received_date": d(-30),
                "lines": [{"purchase_order_line_id": po["lines"][0]["id"], "quantity_received": qty}],
            },
        )

    def invoice(inv_no: str, vendor: dict[str, Any], currency: str, qty: str, price: str, total: str, desc: str,
                po: dict[str, Any] | None = None, inv_offset: int = -25, due_offset: int = 5) -> dict[str, Any] | None:
        line: dict[str, Any] = {"line_number": 1, "description": desc, "quantity": qty, "unit_price": price}
        body: dict[str, Any] = {
            "invoice_number": inv_no, "vendor_id": vendor["id"], "currency": currency,
            "subtotal": total, "tax_amount": "0", "total_amount": total,
            "invoice_date": d(inv_offset), "due_date": d(due_offset), "lines": [line],
        }
        if po:
            body["purchase_order_id"] = po["id"]
            line["purchase_order_line_id"] = po["lines"][0]["id"]
        return ap.call(f"invoice {inv_no}", "POST", "/invoices", json=body)

    v = vendors
    office = v.get("Indus Office Supplies (Demo)")
    it = v.get("Crescent IT Solutions (Demo)")
    pack = v.get("Karachi Packaging Co (Demo)")
    logi = v.get("Sindh Logistics Pvt Ltd (Demo)")
    gulf = v.get("Gulf Stationers FZE (Demo)")

    # 1. Clean three-way match -> approved -> paid
    if office and (po := make_po("PO-DEMO-001", office, "PKR", "25", "18500.00", "A4 paper cartons")):
        receive("GRPO-DEMO-001", po, "25")
        if inv := invoice("INV-DEMO-001", office, "PKR", "25", "18500.00", "462500.00", "A4 paper cartons", po):
            run_agent(inv, "INV-DEMO-001 (clean match)")
            if director.call("approve INV-DEMO-001", "POST", f"/invoices/{inv['id']}/approve"):
                pay = ap.call("schedule payment INV-DEMO-001", "POST", "/payments",
                              json={"invoice_id": inv["id"], "payment_method": "bank_transfer", "scheduled_date": d(0)})
                if pay:
                    director.call("execute payment INV-DEMO-001", "POST", f"/payments/{pay['id']}/execute")

    # 2. Clean match, left waiting for approval (shows up in the approval inbox / payables)
    if it and (po := make_po("PO-DEMO-002", it, "PKR", "4", "275000.00", "Laptop docking stations")):
        receive("GRPO-DEMO-002", po, "4")
        if inv := invoice("INV-DEMO-002", it, "PKR", "4", "275000.00", "1100000.00", "Laptop docking stations", po, -12, 18):
            run_agent(inv, "INV-DEMO-002 (awaiting approval)")

    # 3. Price mismatch: invoice price is 12% above the PO price
    if pack and (po := make_po("PO-DEMO-003", pack, "PKR", "20", "5000.00", "Corrugated boxes")):
        receive("GRPO-DEMO-003", po, "20")
        if inv := invoice("INV-DEMO-003", pack, "PKR", "20", "5600.00", "112000.00", "Corrugated boxes", po, -20, 10):
            run_agent(inv, "INV-DEMO-003 (price mismatch)")

    # 4. Short receipt: invoiced for 100, only 60 received
    if logi and (po := make_po("PO-DEMO-004", logi, "PKR", "100", "1200.00", "Pallet handling")):
        receive("GRPO-DEMO-004", po, "60")
        if inv := invoice("INV-DEMO-004", logi, "PKR", "100", "1200.00", "120000.00", "Pallet handling", po, -15, 0):
            run_agent(inv, "INV-DEMO-004 (short receipt)")

    # 5. Duplicate invoice (same vendor, same number) -> critical
    if it:
        invoice("INV-DEMO-005", it, "PKR", "1", "85000.00", "85000.00", "Annual support retainer", None, -18, 12)
        if dup := invoice("INV-DEMO-005", it, "PKR", "1", "85000.00", "85000.00", "Annual support retainer", None, -17, 13):
            run_agent(dup, "INV-DEMO-005 duplicate")

    # 6. Overdue invoice with no PO, plus a USD invoice
    if pack:
        if inv := invoice("INV-DEMO-006", pack, "PKR", "1", "64000.00", "64000.00", "Pallet wrap supply", None, -55, -25):
            run_agent(inv, "INV-DEMO-006 (overdue)")
    if gulf:
        if inv := invoice("INV-DEMO-007", gulf, "USD", "50", "42.00", "2100.00", "Executive notebooks", None, -10, 20):
            run_agent(inv, "INV-DEMO-007 (USD)")
    if logi:
        invoice("INV-DEMO-008", logi, "PKR", "1", "38500.00", "38500.00", "Fuel surcharge", None, -2, 13)  # left 'received'


# ----------------------------------------------------------------------------- AR scenarios
def seed_ar(ar: Api, run_agents: bool) -> dict[str, dict[str, Any]]:
    print("\nAccounts receivable")
    specs = [
        ("Karachi Textile Exports (Demo)", "PKR", "2000000"),
        ("Lahore Auto Parts Trading (Demo)", "PKR", "500000"),
        ("Sindh Agro Traders (Demo)", "PKR", "100000"),
        ("Gulf Trading FZE (Demo)", "USD", "50000"),
    ]
    customers: dict[str, dict[str, Any]] = {}
    for name, currency, limit in specs:
        slug = name.split(" (")[0].lower().replace(" ", "-")
        customer = ar.call(
            f"customer {name}", "POST", "/customers",
            json={"name": name, "email": f"finance@{slug}.example.com", "default_currency": currency,
                  "payment_terms_days": 30, "credit_limit": limit},
        )
        if customer:
            customers[name] = customer

    invoices: dict[str, dict[str, Any]] = {}

    def ar_invoice(number: str, cust: str, currency: str, amount: str, inv_off: int, due_off: int) -> dict[str, Any] | None:
        customer = customers.get(cust)
        if not customer:
            return None
        inv = ar.call(
            f"AR invoice {number}", "POST", "/ar-invoices",
            json={
                "invoice_number": number, "customer_id": customer["id"], "currency": currency,
                "subtotal": amount, "tax_amount": "0", "total_amount": amount,
                "invoice_date": d(inv_off), "due_date": d(due_off),
                "lines": [{"line_number": 1, "description": "Services and goods supplied", "quantity": "1", "unit_price": amount}],
            },
        )
        if inv and ar.call(f"send {number}", "POST", f"/ar-invoices/{inv['id']}/send"):
            invoices[number] = inv
            return inv
        return None

    def receipt(number: str, amount: str, reference: str) -> None:
        inv = invoices.get(number)
        if inv:
            ar.call(
                f"incoming payment {reference}", "POST", "/incoming-payments",
                json={"ar_invoice_id": inv["id"], "amount": amount, "payment_method": "bank_transfer",
                      "received_date": d(-3), "bank_reference": reference},
            )

    tex, auto, agro, gulf = (s[0] for s in specs)
    ar_invoice("ARINV-DEMO-001", tex, "PKR", "450000.00", -60, -30)     # partly paid, overdue
    receipt("ARINV-DEMO-001", "200000.00", "BR-DEMO-001")
    ar_invoice("ARINV-DEMO-002", tex, "PKR", "320000.00", -10, 20)      # current
    ar_invoice("ARINV-DEMO-008", tex, "PKR", "600000.00", -45, -15)     # paid in full
    receipt("ARINV-DEMO-008", "600000.00", "BR-DEMO-008")
    ar_invoice("ARINV-DEMO-003", auto, "PKR", "280000.00", -100, -70)   # 61-90 days overdue
    ar_invoice("ARINV-DEMO-004", auto, "PKR", "150000.00", -160, -130)  # 90+ days overdue
    ar_invoice("ARINV-DEMO-005", agro, "PKR", "250000.00", -5, 25)      # over the 100,000 credit limit
    ar_invoice("ARINV-DEMO-006", gulf, "USD", "12500.00", -35, -5)      # USD, slightly overdue
    ar_invoice("ARINV-DEMO-007", gulf, "USD", "8000.00", -20, 10)       # USD, paid in full
    receipt("ARINV-DEMO-007", "8000.00", "BR-DEMO-007")

    if run_agents:
        for number in ("ARINV-DEMO-001", "ARINV-DEMO-003", "ARINV-DEMO-005", "ARINV-DEMO-006"):
            if number in invoices:
                ar.call(f"AR agent on {number}", "POST", "/agents/accounts-receivable/run",
                        json={"ar_invoice_id": invoices[number]["id"]})
    return customers


# ----------------------------------------------------------------------------- bank + budgets
def seed_bank_and_budgets(director: Api) -> None:
    print("\nBank statement and budgets")
    director.call(
        "bank statement (references and amount-only lines)", "POST", "/bank-reconciliation/statement-lines",
        json={
            "statement_label": "Demo Bank - current month",
            "lines": [
                {"transaction_date": d(-3), "description": "Incoming wire BR-DEMO-008 Karachi Textile",
                 "amount": "600000.00", "currency": "PKR", "bank_reference": "BR-DEMO-008"},
                {"transaction_date": d(-3), "description": "Incoming wire BR-DEMO-007 Gulf Trading",
                 "amount": "8000.00", "currency": "USD", "bank_reference": "BR-DEMO-007"},
                {"transaction_date": d(-3), "description": "Customer transfer, no reference",
                 "amount": "200000.00", "currency": "PKR"},
                {"transaction_date": d(-1), "description": "Unidentified cash deposit",
                 "amount": "87500.00", "currency": "PKR"},
            ],
        },
    )
    for name, code, start, end, amount, currency in [
        ("Demo - Current month general expense (PKR)", "5000-EXP", TODAY.replace(day=1), TODAY.replace(day=28), "1200000.00", "PKR"),
        ("Demo - Current month general expense (USD)", "5000-EXP", TODAY.replace(day=1), TODAY.replace(day=28), "5000.00", "USD"),
    ]:
        director.call(
            f"budget {name}", "POST", "/budgets",
            json={"name": name, "account_code": code, "period_start": start.isoformat(),
                  "period_end": end.isoformat(), "budgeted_amount": amount, "currency": currency},
        )


# ----------------------------------------------------------------------------- main
def main() -> int:
    parser = argparse.ArgumentParser(description="Seed fake demo data into a local Finance AI Platform.")
    parser.add_argument("--skip-agents", action="store_true", help="do not run the AI agents (faster)")
    args = parser.parse_args()
    run_agents = not args.skip_agents

    print("Preparing demo users")
    if not asyncio.run(ensure_users()):
        return 1

    with httpx.Client(timeout=180.0) as client:
        try:
            client.get(f"{API}/health/live")
        except httpx.HTTPError:
            print(f"\nCannot reach the API at {API}. Start it first: uvicorn app.main:app --reload")
            return 1

        ap, ar, director = Api("ap", client), Api("ar", client), Api("director", client)
        if not all(api.login() for api in (ap, ar, director)):
            return 1

        existing = ap.call("check for earlier demo data", "GET", "/vendors", params={"page": 1, "page_size": 100})
        if existing and any("(Demo)" in item["name"] for item in existing.get("items", [])):
            print("\nDemo data is already present. Nothing to do.")
            return 0

        seed_ap(ap, director, run_agents)
        seed_ar(ar, run_agents)
        seed_bank_and_budgets(director)

    print(f"\nDone: {REPORT.ok} steps succeeded, {len(REPORT.failed)} failed.")
    if REPORT.failed:
        print("Failed steps (send these to Claude if you want them fixed):")
        for line in REPORT.failed:
            print(f"  - {line[:400]}")
    print(
        "\nDemo logins (password for all three: " + DEMO_PASSWORD + ")\n"
        "  demo.director@example.com  approves and executes\n"
        "  demo.ap@example.com        accounts payable clerk\n"
        "  demo.ar@example.com        accounts receivable clerk\n"
        "Your own account (finance_director) also sees all of this data."
    )
    return 0 if not REPORT.failed else 2


if __name__ == "__main__":
    raise SystemExit(main())