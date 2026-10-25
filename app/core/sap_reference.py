"""
app.core.sap_reference
=========================
Reference constants for the future SAP Business One Service Layer/DI API
integration (the SAPIntegrationAgent, Phase 2). This module doesn't call
SAP — it has zero network code — it exists so that every model built up
to now uses vocabulary and a `sap_doc_entry` field that already line up
with SAP B1's own document model, instead of the integration agent
having to invent a mapping layer from scratch later.

*** VERIFY BEFORE PRODUCTION USE ***
Object type codes below are the standard values documented across SAP
Business One DI API / Service Layer references, but SAP has shipped
multiple major versions (9.x, 10.0 FP/PL) and localizations, and object
type codes have occasionally shifted for a handful of document types
between versions. Confirm every code against the target customer's
actual SAP B1 version (Administration -> System Information in the SAP
client, or the Service Layer $metadata endpoint) before wiring the
SAPIntegrationAgent to a real tenant. Treat this file as a strong
starting point, not a substitute for that verification.

DOCUMENT TYPE MAPPING
------------------------
This platform's model  | SAP B1 document        | DI API object          | Service Layer resource | Object type code
------------------------|-------------------------|--------------------------|---------------------------|-------------------
PurchaseOrder            | Purchase Order           | oPurchaseOrders          | PurchaseOrders             | 22
GoodsReceipt (GRPO)      | Goods Receipt PO         | oPurchaseDeliveryNotes   | PurchaseDeliveryNotes      | 20
Invoice (AP Invoice)     | A/P Invoice              | oPurchaseInvoices        | PurchaseInvoices           | 18
APCreditMemo             | A/P Credit Memo          | oPurchaseCreditNotes     | PurchaseCreditNotes        | 19
ARInvoice                | A/R Invoice              | oInvoices                | Invoices                   | 13
ARCreditMemo             | A/R Credit Memo          | oCreditNotes             | CreditNotes                | 14
OutgoingPayment          | Outgoing Payment         | oVendorPayments          | VendorPayments             | 46 (verify)
IncomingPayment          | Incoming Payment         | oIncomingPayments        | IncomingPayments           | 24
JournalEntry             | Journal Entry            | oJournalEntries          | JournalEntries             | 30
Vendor                   | Business Partner (CardType='S') | oBusinessPartners | BusinessPartners           | n/a (master data)
Customer                 | Business Partner (CardType='C') | oBusinessPartners | BusinessPartners           | n/a (master data)

FIELD NAMING NOTES FOR THE FUTURE INTEGRATION AGENT
--------------------------------------------------------
- SAP's `DocEntry` (internal, immutable numeric key) maps to this
  platform's `sap_doc_entry` column, present on every document model
  precisely for this purpose.
- SAP's `DocNum` (the human-visible, sequence-per-series document
  number) maps conceptually to this platform's `*_number` fields
  (`po_number`, `invoice_number`, `credit_memo_number`, ...) — but note
  SAP's `DocNum` is scoped per document series, not globally unique the
  way this platform's number generator (`app.services.numbering`)
  produces values; the sync layer will need to decide whether to adopt
  SAP's numbering as the source of truth post-sync or keep both.
- SAP's `CardCode` maps to `sap_business_partner_code` on both `Vendor`
  and `Customer`.
- SAP Business Partners are one table distinguished by `CardType`; this
  platform keeps `Vendor`/`Customer` separate — see the design note in
  `app.db.models.customer` for why, and how the sync maps both
  directions cleanly regardless.

This mapping intentionally covers documents only through what's modeled
today (Phase 1). Additional SAP document types (Sales Orders, sales
Delivery Notes, Inventory Transfers, Production Orders) get their own
entry here once/if this platform models the corresponding domain
object.
"""

from __future__ import annotations

from enum import IntEnum


class SAPObjectType(IntEnum):
    """SAP B1 DI API `BoObjectTypes` values relevant to documents this
    platform already models. See module docstring for the full mapping
    table and the verification warning."""

    PURCHASE_ORDER = 22
    GOODS_RECEIPT_PO = 20
    AP_INVOICE = 18
    AP_CREDIT_MEMO = 19
    AR_INVOICE = 13
    AR_CREDIT_MEMO = 14
    INCOMING_PAYMENT = 24
    JOURNAL_ENTRY = 30
    # Outgoing payment object type has varied across SAP B1 versions in
    # public documentation — verify against the target tenant before use.
    OUTGOING_PAYMENT = 46


class SAPServiceLayerResource:
    """Service Layer (OData-style REST) resource path segments, for
    reference when the SAPIntegrationAgent is built. Plain string
    constants, not an Enum, since they're used directly as URL path
    segments."""

    PURCHASE_ORDERS = "PurchaseOrders"
    PURCHASE_DELIVERY_NOTES = "PurchaseDeliveryNotes"  # Goods Receipt PO
    PURCHASE_INVOICES = "PurchaseInvoices"  # AP Invoice
    PURCHASE_CREDIT_NOTES = "PurchaseCreditNotes"  # AP Credit Memo
    INVOICES = "Invoices"  # AR Invoice
    CREDIT_NOTES = "CreditNotes"  # AR Credit Memo
    INCOMING_PAYMENTS = "IncomingPayments"
    VENDOR_PAYMENTS = "VendorPayments"  # a.k.a. Outgoing Payments in some versions
    JOURNAL_ENTRIES = "JournalEntries"
    BUSINESS_PARTNERS = "BusinessPartners"  # Vendors + Customers, filtered by CardType


class SAPCardType:
    """Business Partner CardType values — how SAP distinguishes a
    Vendor from a Customer within its single BusinessPartners table.
    Used by the sync layer to decide whether a given BusinessPartners
    record maps to this platform's Vendor or Customer table."""

    CUSTOMER = "cCustomer"
    VENDOR = "cSupplier"
    LEAD = "cLead"


class SAPInvoiceType:
    """Values for the `InvoiceType` field inside a payment's
    `PaymentInvoices` array — how SAP links a payment to the specific
    invoice(s) it settles. *** VERIFY against the target SAP B1 version
    before use, same caveat as SAPObjectType — this is the value set
    commonly documented for SAP B1's DI API, but payment-to-invoice
    linkage is one of the more version-sensitive corners of the Service
    Layer schema. ***"""

    AP_INVOICE = "it_PurchaseInvoice"
    AR_INVOICE = "it_Invoice"
