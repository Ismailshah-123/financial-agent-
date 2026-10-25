"""
app.db.models
=============
Imports every ORM model so that:

    1. `Base.metadata` (in app.db.base) knows about all of them —
       required for `app.db.init_db.create_all()` and for Alembic
       autogenerate to detect the full schema.
    2. SQLAlchemy can resolve the string-based forward references used
       in `relationship(...)` calls (e.g. `Mapped["Vendor"]` in
       purchase_order.py) — these are only resolvable once every
       referenced class has actually been imported into the same
       declarative registry, which happens here, once, at import time.

IMPORTANT: any new model file added under `app/db/models/` must be
imported here, or it will silently be invisible to `create_all()` and
to `alembic revision --autogenerate`. This is the single most common
cause of "why didn't my new table get created" bugs in SQLAlchemy
projects — the fix is always "did you import the model somewhere that
actually runs before create_all/autogenerate."
"""

from app.db.models.vendor import Vendor
from app.db.models.customer import Customer
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.db.models.goods_receipt import GoodsReceipt, GoodsReceiptLine
from app.db.models.invoice import Invoice, InvoiceLine
from app.db.models.ar_invoice import ARInvoice, ARInvoiceLine
from app.db.models.credit_memo import ARCreditMemo, ARCreditMemoLine, APCreditMemo, APCreditMemoLine
from app.db.models.payment import OutgoingPayment
from app.db.models.incoming_payment import IncomingPayment
from app.db.models.journal_entry import JournalEntry, JournalEntryLine
from app.db.models.chart_of_account import ChartOfAccount
from app.db.models.tax_code import TaxCode
from app.db.models.period_close import PeriodClose
from app.db.models.bank_statement_line import BankStatementLine
from app.db.models.budget import Budget
from app.db.models.fbr_remittance import FBRRemittance
from app.db.models.approval_request import ApprovalRequestRecord
from app.db.models.audit_log import AuditLog, AuditChainState
from app.db.models.user import User
from app.db.models.user_session import UserSession

__all__ = [
    "Vendor",
    "Customer",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "GoodsReceipt",
    "GoodsReceiptLine",
    "Invoice",
    "InvoiceLine",
    "ARInvoice",
    "ARInvoiceLine",
    "ARCreditMemo",
    "ARCreditMemoLine",
    "APCreditMemo",
    "APCreditMemoLine",
    "OutgoingPayment",
    "IncomingPayment",
    "JournalEntry",
    "JournalEntryLine",
    "ChartOfAccount",
    "TaxCode",
    "PeriodClose",
    "BankStatementLine",
    "Budget",
    "FBRRemittance",
    "ApprovalRequestRecord",
    "AuditLog",
    "AuditChainState",
    "User",
    "UserSession",
]
