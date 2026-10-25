"""
app.core.constants
===================
Every enum and fixed constant that more than one layer of the platform
needs to agree on lives here. Centralizing them prevents the classic
multi-session drift bug (one file defines `RiskLevel.HIGH = "high"`,
another defines `"HIGH"`, and nothing matches at runtime).

Sections:
    - RBAC: roles and permissions
    - Agents: agent identity and lifecycle states
    - AI decisions: confidence/risk/approval vocabulary required by every
      agent decision (per the platform's "AI must never transact without
      approval" rule)
    - Finance domain: transaction/document/currency vocabulary
    - System-wide limits
"""

from __future__ import annotations

from enum import Enum


# --------------------------------------------------------------------------
# RBAC / ABAC
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    """Coarse-grained roles. Fine-grained access uses Permission + ABAC
    attribute checks (department, cost center, approval limit) on top of
    this, evaluated in app.core.security."""

    SUPER_ADMIN = "super_admin"
    FINANCE_DIRECTOR = "finance_director"
    FINANCE_MANAGER = "finance_manager"
    ACCOUNTANT = "accountant"
    AP_CLERK = "ap_clerk"
    AR_CLERK = "ar_clerk"
    AUDITOR = "auditor"
    APPROVER = "approver"
    VIEWER = "viewer"


class Permission(str, Enum):
    """Fine-grained, resource-scoped permissions. Format: `<domain>:<action>`."""

    VENDOR_READ = "vendor:read"
    VENDOR_CREATE = "vendor:create"
    VENDOR_MANAGE = "vendor:manage"  # update vendor records, activate/block
    VENDOR_BANK_DETAILS_READ = "vendor:bank_details:read"  # view vendor bank coordinates
    PURCHASE_ORDER_READ = "purchase_order:read"
    PURCHASE_ORDER_CREATE = "purchase_order:create"
    GOODS_RECEIPT_CREATE = "goods_receipt:create"
    INVOICE_READ = "invoice:read"
    INVOICE_CREATE = "invoice:create"
    INVOICE_APPROVE = "invoice:approve"
    PAYMENT_READ = "payment:read"
    PAYMENT_INITIATE = "payment:initiate"
    PAYMENT_APPROVE = "payment:approve"
    JOURNAL_ENTRY_CREATE = "journal_entry:create"
    JOURNAL_ENTRY_POST = "journal_entry:post"
    REPORT_VIEW = "report:view"
    REPORT_EXPORT = "report:export"
    AGENT_INVOKE = "agent:invoke"
    AGENT_CONFIGURE = "agent:configure"
    AUDIT_LOG_READ = "audit_log:read"
    ADMIN_USER_MANAGE = "admin:user_manage"

    # Accounts Receivable
    CUSTOMER_READ = "customer:read"
    CUSTOMER_CREATE = "customer:create"
    CUSTOMER_MANAGE = "customer:manage"
    AR_INVOICE_READ = "ar_invoice:read"
    AR_INVOICE_CREATE = "ar_invoice:create"
    AR_INVOICE_APPROVE = "ar_invoice:approve"
    CREDIT_MEMO_READ = "credit_memo:read"
    CREDIT_MEMO_CREATE = "credit_memo:create"
    CREDIT_MEMO_APPROVE = "credit_memo:approve"

    # Tax
    TAX_CODE_READ = "tax_code:read"
    TAX_CODE_MANAGE = "tax_code:manage"  # create/update tax codes and rates

    # Period close
    PERIOD_CLOSE_READ = "period_close:read"
    PERIOD_CLOSE_EXECUTE = "period_close:execute"  # close or reopen a period

    # Bank reconciliation
    BANK_STATEMENT_READ = "bank_statement:read"
    BANK_STATEMENT_INGEST = "bank_statement:ingest"  # upload statement lines
    BANK_STATEMENT_MATCH = "bank_statement:match"  # confirm a match

    # Budget planning
    BUDGET_READ = "budget:read"
    BUDGET_MANAGE = "budget:manage"  # create budgets

    # FBR remittance / compliance
    FBR_REMITTANCE_READ = "fbr_remittance:read"
    FBR_REMITTANCE_RECORD = "fbr_remittance:record"  # record a remittance to FBR

    # Approval inbox
    APPROVAL_REQUEST_READ = "approval_request:read"
    APPROVAL_REQUEST_ACTION = "approval_request:action"  # approve or reject


# --------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------
class AgentType(str, Enum):
    """Every specialized agent the platform composes. New agents get added
    here first — this is the canonical registry other modules key off of."""

    FINANCE_DIRECTOR = "finance_director"
    ACCOUNTS_PAYABLE = "accounts_payable"
    ACCOUNTS_RECEIVABLE = "accounts_receivable"
    TAX = "tax"
    TREASURY = "treasury"
    BANK_RECONCILIATION = "bank_reconciliation"
    COLLECTIONS = "collections"
    AUDIT = "audit"
    COMPLIANCE = "compliance"
    INVOICE_PROCESSING = "invoice_processing"
    FRAUD_DETECTION = "fraud_detection"
    FINANCIAL_REPORTING = "financial_reporting"
    BUDGET_PLANNING = "budget_planning"
    APPROVAL_WORKFLOW = "approval_workflow"
    SAP_INTEGRATION = "sap_integration"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    EMAIL = "email"
    VOICE = "voice"
    OCR = "ocr"
    ANALYTICS = "analytics"


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# --------------------------------------------------------------------------
# AI decision vocabulary — mandatory fields on every agent output
# --------------------------------------------------------------------------
class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"




class ApprovalExecutionStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    EXECUTION_PENDING = "execution_pending"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"


class ApprovalActionType(str, Enum):
    """Typed commands that the approval engine may execute.

    An approval record without an action type is deliberately non-executable.
    This prevents free-text AI recommendations from becoming arbitrary server
    method calls. New commands must be added here and to the execution registry.
    """

    PAYMENT_EXECUTE = "payment_execute"

class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    EXPIRED = "expired"


# --------------------------------------------------------------------------
# Finance domain
# --------------------------------------------------------------------------
class TransactionType(str, Enum):
    AP_INVOICE = "ap_invoice"
    AR_INVOICE = "ar_invoice"
    INCOMING_PAYMENT = "incoming_payment"
    OUTGOING_PAYMENT = "outgoing_payment"
    JOURNAL_ENTRY = "journal_entry"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"
    PURCHASE_ORDER = "purchase_order"
    GOODS_RECEIPT = "goods_receipt"
    PERIOD_CLOSE = "period_close"


class DocumentType(str, Enum):
    INVOICE = "invoice"
    PURCHASE_ORDER = "purchase_order"
    GRPO = "grpo"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"
    TAX_CERTIFICATE = "tax_certificate"
    BANK_STATEMENT = "bank_statement"
    RECEIPT = "receipt"
    FINANCIAL_REPORT = "financial_report"
    CONTRACT = "contract"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    PKR = "PKR"
    AED = "AED"
    SAR = "SAR"


# --------------------------------------------------------------------------
# System-wide limits
# --------------------------------------------------------------------------
MAX_UPLOAD_FILE_SIZE_MB = 25
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
CORRELATION_ID_HEADER = "X-Correlation-ID"
