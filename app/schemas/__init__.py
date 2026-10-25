"""
app.schemas
===========
Pydantic request/response models for the HTTP API (distinct from
`app.agents.schemas`, which models agent decisions, and from
`app.db.models`, which models persisted ORM rows). Kept as its own layer
so the wire format can evolve independently of both the database schema
and the internal agent contracts — a classic Clean Architecture boundary.

Modules:
    common.py          — APIModel base config, pagination envelope
    vendor.py           — VendorCreate / VendorUpdate / VendorRead
    purchase_order.py   — PurchaseOrderCreate / PurchaseOrderRead (+ lines)
    goods_receipt.py    — GoodsReceiptCreate / GoodsReceiptRead (+ lines)
    invoice.py           — InvoiceCreate / InvoiceRead (+ lines)
    payment.py           — PaymentCreate / PaymentRead
    journal_entry.py     — JournalEntryRead (read-only; see module docstring)
    user.py               — UserCreate / UserRead
    auth.py               — LoginRequest / RefreshRequest / TokenResponse
    agent.py               — RunAccountsPayableAgentRequest
    customer.py             — CustomerCreate / CustomerUpdate / CustomerRead (AR)
    ar_invoice.py            — ARInvoiceCreate / ARInvoiceRead (+ lines)
    credit_memo.py            — ARCreditMemoCreate/Read, APCreditMemoCreate/Read

Every `*Read` schema is built via `from_attributes=True`
(`VendorRead.model_validate(vendor_row)`) directly off the corresponding
SQLAlchemy model in `app.db.models` — see `app.schemas.common.APIModel`.
"""
