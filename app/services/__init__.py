"""
app.services
============
Application/use-case layer. Services orchestrate repositories and
external systems to fulfill one business use case each; this is where
business rules and invariants live (balanced journal entries, PO/GRPO
quantity reconciliation, duplicate-invoice detection) — not in the API
routers and not in the ORM models.

Modules:
    numbering.py               — human-readable document number generation
    vendor_service.py           — vendor onboarding/activation
    purchase_order_service.py   — PO creation (owns total_amount computation)
    goods_receipt_service.py    — GRPO creation, PO status roll-up
    matching_service.py         — InvoiceMatchingEngine (2-way/3-way match;
                                   deterministic, no LLM — see its docstring
                                   for why this is a service, not agent logic)
    invoice_service.py          — invoice ingestion, duplicate detection,
                                   status transitions
    posting_service.py          — the ONLY place JournalEntry rows are
                                   created; enforces debit == credit
    payment_service.py          — payment scheduling + execution (simulated
                                   settlement in this phase)
    auth_service.py              — registration, login, refresh-token exchange
    customer_service.py           — customer onboarding/activation (AR mirror
                                   of vendor_service.py)
    ar_invoice_service.py          — AR invoice ingestion + issuance (posts
                                   immediately on send — no approval gate,
                                   see its docstring for why)
    credit_memo_service.py          — AR and AP credit memo issuance +
                                   approval-gated application (updates
                                   ARInvoice.amount_credited via
                                   ARInvoiceService.apply_balance_change)
    incoming_payment_service.py      — records customer payments against AR
                                   invoices (updates ARInvoice.amount_paid
                                   via the same apply_balance_change)
    sap_sync_service.py               — syncs Vendor/Customer to SAP Business
                                   One via app.integrations.sap; detects
                                   conflicts rather than auto-resolving
                                   them (see its docstring)
    financial_reporting_service.py     — Trial Balance, Profit & Loss, and
                                   Balance Sheet computed from posted
                                   journal entries (see its docstring for
                                   the Balance Sheet equity limitation)
    tax_service.py                     — sales tax + withholding tax
                                   calculation (PKR/FBR-oriented seed data,
                                   configurable for any jurisdiction — see
                                   its docstring on the sales-tax-vs-
                                   withholding-tax distinction)

API routers call services; services never import from `app.api`. The
`AccountsPayableAgent` (next: prompts -> agents) calls
`InvoiceMatchingEngine` directly for its deterministic matching step and
calls `InvoiceService`/`PaymentService` to persist the outcome of its
decisions once approved.
"""
