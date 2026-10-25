"""
app.integrations.sap.document_mappers
========================================
Pure functions mapping this platform's transactional documents
(PurchaseOrder, Invoice) to SAP Service Layer document JSON. Separate
from `mappers.py` (which handles master data — Vendor/Customer as SAP
BusinessPartners) because document mapping has a structural concern
master-data mapping doesn't: line items, and — for AP invoices drawn
against a PO — SAP's "base document" linkage (`BaseType`/`BaseEntry`/
`BaseLine`), which is how SAP itself represents a 3-way match on its
side once synced, mirroring what `InvoiceMatchingEngine`
(`app.services.matching_service`) already does on this platform's side.

*** SAME VERIFICATION CAVEAT AS EVERY OTHER FILE IN app.integrations.sap:
these mappings follow SAP's publicly documented Service Layer schema
but have not been exercised against a real SAP B1 instance. Field
coverage is partial — SAP's PurchaseOrders/PurchaseInvoices objects
support tax codes, warehouses, price lists, and many more fields than
this platform's own models currently carry. Extend field-by-field
against a real customer's SAP configuration, not speculatively. ***

SAP LINE NUMBERING: SAP's `DocumentLines[].LineNum` is 0-INDEXED. This
platform's `PurchaseOrderLine.line_number` / `InvoiceLine.line_number`
are 1-INDEXED (see those models). Every function here does the
conversion (`line_number - 1`) explicitly — this is a well-known SAP
integration gotcha and getting it wrong silently misaligns goods-receipt
and invoice matching inside SAP itself, so it is called out here rather
than left implicit in a subtraction buried in a list comprehension.

BASE-DOCUMENT LINKAGE IS BEST-EFFORT, NEVER PARTIALLY WRONG: an invoice
line can only carry `BaseType`/`BaseEntry`/`BaseLine` if the caller
supplies `po_line_numbers_by_local_line_id` — a mapping from this
platform's local `PurchaseOrderLine.id` to that PO line's own
`line_number`, needed because an invoice line only knows the *local*
`PurchaseOrderLine.id` it matched against, not the PO line's SAP-side
position. If that mapping is missing or doesn't contain a given line's
PO line id, this function omits the base fields for that line entirely
(a valid, standalone document line in SAP) rather than sending a
guessed or null `BaseLine`, which SAP would either reject or — worse —
silently misassociate. `SAPSyncService.sync_ap_invoice` is what builds
that mapping correctly before calling this function.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.sap_reference import SAPInvoiceType, SAPObjectType
from app.db.models.ar_invoice import ARInvoice
from app.db.models.credit_memo import ARCreditMemo
from app.db.models.incoming_payment import IncomingPayment
from app.db.models.invoice import Invoice
from app.db.models.payment import OutgoingPayment
from app.db.models.purchase_order import PurchaseOrder


def purchase_order_to_sap(po: PurchaseOrder, *, vendor_card_code: str) -> dict[str, Any]:
    """Builds the SAP `PurchaseOrders` create payload. `vendor_card_code`
    must be the vendor's ALREADY-SYNCED SAP CardCode — this function
    does not sync the vendor itself; `SAPSyncService.sync_purchase_order`
    is responsible for ensuring that happened first (see its docstring)."""
    return {
        "CardCode": vendor_card_code,
        "DocDate": po.order_date.isoformat(),
        "DocDueDate": (po.expected_delivery_date or po.order_date).isoformat(),
        "DocCurrency": po.currency,
        "NumAtCard": po.po_number,  # vendor-visible reference number
        "DocumentLines": [
            {
                "LineNum": line.line_number - 1,  # SAP is 0-indexed — see module docstring
                "ItemDescription": line.description,
                "Quantity": float(line.quantity_ordered),
                "UnitPrice": float(line.unit_price),
            }
            for line in po.lines
        ],
    }


def ap_invoice_to_sap(
    invoice: Invoice,
    *,
    vendor_card_code: str,
    purchase_order_sap_doc_entry: int | None = None,
    po_line_numbers_by_local_line_id: dict[uuid.UUID, int] | None = None,
) -> dict[str, Any]:
    """Builds the SAP `PurchaseInvoices` create payload. When both
    `purchase_order_sap_doc_entry` and `po_line_numbers_by_local_line_id`
    are provided, each invoice line whose `purchase_order_line_id` is
    present in that mapping gets SAP's base-document linkage — the
    SAP-side equivalent of this platform's own 3-way match. Any line
    without a resolvable mapping is sent as a standalone line (valid,
    just without PO traceability inside SAP) — see module docstring for
    why this is a deliberate safe fallback, not a bug."""
    po_line_numbers_by_local_line_id = po_line_numbers_by_local_line_id or {}

    lines: list[dict[str, Any]] = []
    for line in invoice.lines:
        line_payload: dict[str, Any] = {
            "LineNum": line.line_number - 1,
            "ItemDescription": line.description,
            "Quantity": float(line.quantity),
            "UnitPrice": float(line.unit_price),
        }
        po_line_number = (
            po_line_numbers_by_local_line_id.get(line.purchase_order_line_id)
            if line.purchase_order_line_id is not None
            else None
        )
        if purchase_order_sap_doc_entry is not None and po_line_number is not None:
            line_payload["BaseType"] = int(SAPObjectType.PURCHASE_ORDER)
            line_payload["BaseEntry"] = purchase_order_sap_doc_entry
            line_payload["BaseLine"] = po_line_number - 1
        lines.append(line_payload)

    return {
        "CardCode": vendor_card_code,
        "DocDate": invoice.invoice_date.isoformat(),
        "DocDueDate": invoice.due_date.isoformat(),
        "DocCurrency": invoice.currency,
        "NumAtCard": invoice.invoice_number,
        "DocumentLines": lines,
    }


def sap_document_response_to_doc_entry(response: dict[str, Any]) -> int | None:
    """Extracts SAP's `DocEntry` from a document create/get response —
    the value this platform stores in `sap_doc_entry` on the
    corresponding local model."""
    value = response.get("DocEntry")
    return int(value) if value is not None else None


# --------------------------------------------------------------------------
# AR side — ARInvoice -> SAP Invoices, ARCreditMemo -> SAP CreditNotes
# --------------------------------------------------------------------------
def ar_invoice_to_sap(ar_invoice: ARInvoice, *, customer_card_code: str) -> dict[str, Any]:
    """Builds the SAP `Invoices` (A/R Invoice) create payload.
    `customer_card_code` must be the customer's already-synced SAP
    CardCode. No base-document linkage here — this platform doesn't
    model a SalesOrder yet (AR's mirror of PurchaseOrder; see
    `app.db.models.ar_invoice`'s docstring), so every AR invoice is a
    standalone document on the SAP side, same as this platform's own
    `Invoice.purchase_order_id=None` (`MatchType.MANUAL`) case on the
    AP side."""
    return {
        "CardCode": customer_card_code,
        "DocDate": ar_invoice.invoice_date.isoformat(),
        "DocDueDate": ar_invoice.due_date.isoformat(),
        "DocCurrency": ar_invoice.currency,
        "NumAtCard": ar_invoice.invoice_number,
        "DocumentLines": [
            {
                "LineNum": line.line_number - 1,
                "ItemDescription": line.description,
                "Quantity": float(line.quantity),
                "UnitPrice": float(line.unit_price),
            }
            for line in ar_invoice.lines
        ],
    }


def ar_credit_memo_to_sap(memo: ARCreditMemo, *, customer_card_code: str) -> dict[str, Any]:
    """Builds the SAP `CreditNotes` (A/R Credit Memo) create payload.

    NO base-document linkage to the related AR invoice is attempted,
    even when `memo.related_ar_invoice_id` is set — unlike
    `ap_invoice_to_sap`'s PO linkage, `ARCreditMemoLine` doesn't carry a
    reference to the specific `ARInvoiceLine` it credits (see
    `app.db.models.credit_memo`; only the memo as a whole references
    the invoice, not each line). Guessing a line-level correspondence
    (e.g. by matching line order) would risk linking the wrong lines in
    SAP, which is worse than no link at all — so this is sent as a
    standalone document. If line-level AR credit traceability becomes a
    real requirement, `ARCreditMemoLine` needs an `ar_invoice_line_id`
    column first (a schema change), not a guess made here."""
    return {
        "CardCode": customer_card_code,
        "DocDate": memo.memo_date.isoformat(),
        "DocCurrency": memo.currency,
        "NumAtCard": memo.credit_memo_number,
        "DocumentLines": [
            {
                "LineNum": line.line_number - 1,
                "ItemDescription": line.description,
                "Quantity": float(line.quantity),
                "UnitPrice": float(line.unit_price),
            }
            for line in memo.lines
        ],
    }


# --------------------------------------------------------------------------
# Payments — OutgoingPayment -> SAP VendorPayments, IncomingPayment ->
# SAP IncomingPayments. Both require a G/L cash/bank account code
# (settings.sap.default_cash_account_code — SAP's own chart of
# accounts, unrelated to this platform's internal posting_service
# account codes) and the settled invoice's own sap_doc_entry, since a
# SAP payment is expressed as "this much applied against that invoice
# DocEntry", not as a standalone transaction.
# --------------------------------------------------------------------------
def outgoing_payment_to_sap(
    payment: OutgoingPayment,
    *,
    vendor_card_code: str,
    ap_invoice_sap_doc_entry: int,
    cash_account_code: str,
) -> dict[str, Any]:
    """Builds the SAP `VendorPayments` create payload. Requires the
    settled AP invoice to already be synced (`ap_invoice_sap_doc_entry`)
    — a payment cannot be linked to an invoice that doesn't exist in
    SAP yet. `cash_account_code` must be a real SAP G/L account code
    (see `SAPSettings.default_cash_account_code`'s docstring); this
    function does not default or guess one."""
    return {
        "CardCode": vendor_card_code,
        "DocDate": (payment.executed_date or payment.scheduled_date).isoformat(),
        "CashAccount": cash_account_code,
        "CashSum": float(payment.amount),
        "PaymentInvoices": [
            {
                "DocEntry": ap_invoice_sap_doc_entry,
                "InvoiceType": SAPInvoiceType.AP_INVOICE,
                "SumApplied": float(payment.amount),
            }
        ],
    }


def incoming_payment_to_sap(
    payment: IncomingPayment,
    *,
    customer_card_code: str,
    ar_invoice_sap_doc_entry: int,
    cash_account_code: str,
) -> dict[str, Any]:
    """Builds the SAP `IncomingPayments` create payload. Same
    requirements as `outgoing_payment_to_sap`, mirrored for the AR
    side."""
    return {
        "CardCode": customer_card_code,
        "DocDate": payment.received_date.isoformat(),
        "CashAccount": cash_account_code,
        "CashSum": float(payment.amount),
        "PaymentInvoices": [
            {
                "DocEntry": ar_invoice_sap_doc_entry,
                "InvoiceType": SAPInvoiceType.AR_INVOICE,
                "SumApplied": float(payment.amount),
            }
        ],
    }
