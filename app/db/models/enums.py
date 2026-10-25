"""
app.db.models.enums
====================
Status enums that belong to *persisted rows*, as opposed to the agent
decision vocabulary in `app.core.constants` (RiskLevel, ApprovalStatus)
which describes an AI decision, not a database record's lifecycle.

Kept separate from `app.core.constants` deliberately: a `PurchaseOrder`
row's `status` column evolves independently of any AI agent involvement
(e.g. `DRAFT` -> `SENT` -> `PARTIALLY_RECEIVED` -> `CLOSED`), and mixing
the two vocabularies in one enum module would make it unclear which
enums are safe to store in the database (need a migration to change)
versus which are pure in-memory agent semantics (safe to extend freely).
"""

from __future__ import annotations

from enum import Enum


class VendorStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"          # e.g. fraud flag, compliance hold
    PENDING_REVIEW = "pending_review"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PARTIALLY_RECEIVED = "partially_received"
    FULLY_RECEIVED = "fully_received"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class GoodsReceiptStatus(str, Enum):
    DRAFT = "draft"
    POSTED = "posted"
    CANCELLED = "cancelled"


class InvoiceStatus(str, Enum):
    RECEIVED = "received"                # ingested, not yet matched
    MATCHING_IN_PROGRESS = "matching_in_progress"
    MATCHED = "matched"                  # 2-way/3-way match succeeded
    MATCH_FAILED = "match_failed"        # discrepancy found, needs human review
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SCHEDULED_FOR_PAYMENT = "scheduled_for_payment"
    PAID = "paid"
    VOID = "void"


class PaymentStatus(str, Enum):
    SCHEDULED = "scheduled"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JournalEntryStatus(str, Enum):
    DRAFT = "draft"
    POSTED = "posted"
    REVERSED = "reversed"


class MatchType(str, Enum):
    """How an invoice was matched before approval — recorded for audit,
    since 2-way and 3-way match carry different risk profiles."""

    TWO_WAY = "two_way"      # invoice <-> purchase order only (no GRPO)
    THREE_WAY = "three_way"  # invoice <-> purchase order <-> goods receipt
    MANUAL = "manual"        # no PO on file; matched/approved by a human


# --------------------------------------------------------------------------
# Accounts Receivable (customer-facing side — see app.db.models.customer,
# app.db.models.ar_invoice, app.db.models.credit_memo)
# --------------------------------------------------------------------------
class CustomerStatus(str, Enum):
    """Deliberately a separate enum from VendorStatus, not a shared
    alias, even though the values are identical today — see the design
    note at the top of app.db.models.customer for why Customer and
    Vendor are kept as separate tables (mirroring how many mid-market
    ERPs model this) rather than a unified BusinessPartner table (which
    is how SAP B1 itself models it, via CardType). Keeping the enums
    separate means either side's status vocabulary can diverge later
    (e.g. a customer-specific 'credit_hold' status) without touching
    the other."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"
    PENDING_REVIEW = "pending_review"


class ARInvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class CreditMemoStatus(str, Enum):
    """Shared by both ARCreditMemo and APCreditMemo — the lifecycle is
    identical on both sides (draft -> posted -> applied against an
    invoice, or void), only which party it's issued to/by differs."""

    DRAFT = "draft"
    POSTED = "posted"
    APPLIED = "applied"
    VOID = "void"


# --------------------------------------------------------------------------
# Chart of Accounts / Financial Reporting
# --------------------------------------------------------------------------
class AccountType(str, Enum):
    """The five fundamental account classifications every double-entry
    system is built on. Which financial statement an account appears
    on, and its normal (debit vs. credit) balance, both derive from
    this — see app.db.models.chart_of_account.ChartOfAccount.normal_side."""

    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


# --------------------------------------------------------------------------
# Tax
# --------------------------------------------------------------------------
class TaxType(str, Enum):
    """Two fundamentally different mechanisms, not two flavors of the
    same thing — see app.services.tax_service's module docstring:

    SALES_TAX: added ON TOP of a subtotal, increasing the invoice
        total (e.g. Pakistan's federal GST under the Sales Tax Act
        1990, or a provincial Sales Tax on Services).
    WITHHOLDING_TAX: DEDUCTED FROM a payment before it reaches the
        payee, then remitted to the tax authority separately (e.g.
        Pakistan's Section 153 withholding under the Income Tax
        Ordinance 2001). This never increases what's billed — it
        changes how much of an already-billed amount actually reaches
        the vendor's bank account.
    """

    SALES_TAX = "sales_tax"
    WITHHOLDING_TAX = "withholding_tax"


class FilerStatus(str, Enum):
    """Whether a vendor is on the active taxpayer list ('filer') for
    withholding tax purposes — Pakistan's Section 153 withholding rates
    differ substantially between filers and non-filers, so this drives
    which TaxCode PaymentService selects when withholding applies. NULL/
    unset on Vendor means unknown — treated as non-filer (the higher,
    more conservative rate) by PaymentService rather than defaulting to
    the lower filer rate, since under-withholding is the costlier
    mistake to get wrong."""

    FILER = "filer"
    NON_FILER = "non_filer"
