"""
app.repositories
=================
Data-access layer (Repository Pattern). Every repository wraps a single
aggregate's persistence behind a small, intention-revealing interface
(`get_by_id`, `list_overdue`, ...) so that `app.services` and
`app.agents` never write raw SQLAlchemy queries directly. This is what
makes services/agents unit-testable with a fake repository instead of a
real Postgres instance, and is the seam where SAP Business One sync will
eventually plug in (a `SapAwareInvoiceRepository` implementing the same
interface).

Modules:
    base_repository.py           — generic CRUD (BaseRepository[ModelT])
    vendor_repository.py          — VendorRepository
    purchase_order_repository.py  — PurchaseOrderRepository
    goods_receipt_repository.py   — GoodsReceiptRepository
    invoice_repository.py         — InvoiceRepository
    payment_repository.py         — PaymentRepository
    journal_entry_repository.py   — JournalEntryRepository
    user_repository.py            — UserRepository
    customer_repository.py        — CustomerRepository (AR mirror of Vendor)
    ar_invoice_repository.py       — ARInvoiceRepository
    credit_memo_repository.py       — ARCreditMemoRepository, APCreditMemoRepository
    incoming_payment_repository.py   — IncomingPaymentRepository
    chart_of_account_repository.py    — ChartOfAccountRepository
    tax_code_repository.py             — TaxCodeRepository (effective-dated
                                   rate lookup)

Every concrete repository takes an `AsyncSession` in its constructor
(`InvoiceRepository(session)`) so all its calls share one
unit-of-work/transaction — see `app.db.session.get_db` /
`session_scope()` for how that session is obtained.
"""
