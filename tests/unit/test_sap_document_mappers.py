"""
Unit tests for app.integrations.sap.document_mappers — pure functions,
no I/O. Particular focus on the two things most likely to be wrong in a
hand-authored SAP mapping: the 0-indexed LineNum conversion, and the
BaseType/BaseEntry/BaseLine linkage only being set when it can be
resolved correctly (never a guessed/null value).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.core.sap_reference import SAPObjectType
from app.db.models.ar_invoice import ARInvoice, ARInvoiceLine
from app.db.models.credit_memo import ARCreditMemo, ARCreditMemoLine
from app.db.models.incoming_payment import IncomingPayment
from app.db.models.invoice import Invoice, InvoiceLine
from app.db.models.payment import OutgoingPayment
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.integrations.sap.document_mappers import (
    ap_invoice_to_sap,
    ar_credit_memo_to_sap,
    ar_invoice_to_sap,
    incoming_payment_to_sap,
    outgoing_payment_to_sap,
    purchase_order_to_sap,
    sap_document_response_to_doc_entry,
)


def _po_line(line_number: int, po_line_id: uuid.UUID | None = None) -> PurchaseOrderLine:
    line = PurchaseOrderLine(
        line_number=line_number,
        description=f"Item {line_number}",
        quantity_ordered=Decimal("10"),
        unit_price=Decimal("50.00"),
        line_total=Decimal("500.00"),
    )
    line.id = po_line_id or uuid.uuid4()
    return line


def _purchase_order(lines: list[PurchaseOrderLine]) -> PurchaseOrder:
    po = PurchaseOrder(
        po_number="PO-TEST-1",
        vendor_id=uuid.uuid4(),
        currency="USD",
        total_amount=Decimal("500.00"),
        order_date=date(2026, 1, 15),
        expected_delivery_date=date(2026, 1, 30),
    )
    po.lines = lines
    return po


def test_purchase_order_to_sap_maps_core_fields_and_zero_indexes_lines() -> None:
    po = _purchase_order([_po_line(1), _po_line(2)])
    payload = purchase_order_to_sap(po, vendor_card_code="V0001")

    assert payload["CardCode"] == "V0001"
    assert payload["DocDate"] == "2026-01-15"
    assert payload["DocDueDate"] == "2026-01-30"
    assert payload["NumAtCard"] == "PO-TEST-1"
    assert len(payload["DocumentLines"]) == 2
    # local line_number 1 -> SAP LineNum 0; local 2 -> SAP 1
    assert payload["DocumentLines"][0]["LineNum"] == 0
    assert payload["DocumentLines"][1]["LineNum"] == 1


def test_purchase_order_to_sap_falls_back_to_order_date_when_no_delivery_date() -> None:
    po = _purchase_order([_po_line(1)])
    po.expected_delivery_date = None
    payload = purchase_order_to_sap(po, vendor_card_code="V0001")
    assert payload["DocDueDate"] == payload["DocDate"]


def _invoice_line(
    line_number: int, po_line_id: uuid.UUID | None = None
) -> InvoiceLine:
    return InvoiceLine(
        line_number=line_number,
        purchase_order_line_id=po_line_id,
        description=f"Item {line_number}",
        quantity=Decimal("10"),
        unit_price=Decimal("50.00"),
        line_total=Decimal("500.00"),
    )


def _invoice(lines: list[InvoiceLine]) -> Invoice:
    inv = Invoice(
        invoice_number="INV-TEST-1",
        vendor_id=uuid.uuid4(),
        currency="USD",
        subtotal=Decimal("500.00"),
        total_amount=Decimal("500.00"),
        invoice_date=date(2026, 2, 1),
        due_date=date(2026, 3, 1),
    )
    inv.lines = lines
    return inv


def test_ap_invoice_to_sap_without_po_link_has_no_base_fields() -> None:
    invoice = _invoice([_invoice_line(1)])
    payload = ap_invoice_to_sap(invoice, vendor_card_code="V0001")

    line = payload["DocumentLines"][0]
    assert "BaseType" not in line
    assert "BaseEntry" not in line
    assert "BaseLine" not in line


def test_ap_invoice_to_sap_with_resolvable_po_link_sets_base_fields() -> None:
    po_line_id = uuid.uuid4()
    invoice = _invoice([_invoice_line(1, po_line_id=po_line_id)])

    payload = ap_invoice_to_sap(
        invoice,
        vendor_card_code="V0001",
        purchase_order_sap_doc_entry=42,
        po_line_numbers_by_local_line_id={po_line_id: 3},  # PO's local line_number = 3
    )

    line = payload["DocumentLines"][0]
    assert line["BaseType"] == int(SAPObjectType.PURCHASE_ORDER)
    assert line["BaseEntry"] == 42
    assert line["BaseLine"] == 2  # 3 - 1, zero-indexed


def test_ap_invoice_to_sap_with_unresolvable_po_link_omits_base_fields() -> None:
    """The invoice line references a PO line, but the caller didn't
    supply a mapping for it (e.g. the PO line lookup failed) — must
    NOT send a guessed or null BaseLine; must omit the base fields
    entirely for that line."""
    po_line_id = uuid.uuid4()
    invoice = _invoice([_invoice_line(1, po_line_id=po_line_id)])

    payload = ap_invoice_to_sap(
        invoice,
        vendor_card_code="V0001",
        purchase_order_sap_doc_entry=42,
        po_line_numbers_by_local_line_id={},  # deliberately empty/unresolved
    )

    line = payload["DocumentLines"][0]
    assert "BaseType" not in line
    assert "BaseEntry" not in line
    assert "BaseLine" not in line


def test_ap_invoice_to_sap_without_doc_entry_omits_base_fields_even_with_mapping() -> None:
    """If the PO itself was never synced (no sap_doc_entry), the base
    link can't be established regardless of whether the line mapping
    exists."""
    po_line_id = uuid.uuid4()
    invoice = _invoice([_invoice_line(1, po_line_id=po_line_id)])

    payload = ap_invoice_to_sap(
        invoice,
        vendor_card_code="V0001",
        purchase_order_sap_doc_entry=None,
        po_line_numbers_by_local_line_id={po_line_id: 1},
    )

    line = payload["DocumentLines"][0]
    assert "BaseType" not in line


def test_sap_document_response_to_doc_entry_extracts_value() -> None:
    assert sap_document_response_to_doc_entry({"DocEntry": 123}) == 123


def test_sap_document_response_to_doc_entry_returns_none_when_missing() -> None:
    assert sap_document_response_to_doc_entry({}) is None


def _ar_invoice_line(line_number: int) -> ARInvoiceLine:
    return ARInvoiceLine(
        line_number=line_number,
        description=f"Service {line_number}",
        quantity=Decimal("1"),
        unit_price=Decimal("1000.00"),
        line_total=Decimal("1000.00"),
    )


def _ar_invoice(lines: list[ARInvoiceLine]) -> ARInvoice:
    inv = ARInvoice(
        invoice_number="ARINV-TEST-1",
        customer_id=uuid.uuid4(),
        currency="USD",
        subtotal=Decimal("1000.00"),
        total_amount=Decimal("1000.00"),
        invoice_date=date(2026, 3, 1),
        due_date=date(2026, 3, 31),
    )
    inv.lines = lines
    return inv


def test_ar_invoice_to_sap_maps_core_fields_and_zero_indexes_lines() -> None:
    invoice = _ar_invoice([_ar_invoice_line(1), _ar_invoice_line(2)])
    payload = ar_invoice_to_sap(invoice, customer_card_code="C0001")

    assert payload["CardCode"] == "C0001"
    assert payload["DocDate"] == "2026-03-01"
    assert payload["DocDueDate"] == "2026-03-31"
    assert payload["NumAtCard"] == "ARINV-TEST-1"
    assert payload["DocumentLines"][0]["LineNum"] == 0
    assert payload["DocumentLines"][1]["LineNum"] == 1


def _ar_credit_memo_line(line_number: int) -> ARCreditMemoLine:
    return ARCreditMemoLine(
        line_number=line_number,
        description=f"Credit {line_number}",
        quantity=Decimal("1"),
        unit_price=Decimal("200.00"),
        line_total=Decimal("200.00"),
    )


def _ar_credit_memo(lines: list[ARCreditMemoLine]) -> ARCreditMemo:
    memo = ARCreditMemo(
        credit_memo_number="ARCM-TEST-1",
        customer_id=uuid.uuid4(),
        currency="USD",
        subtotal=Decimal("200.00"),
        total_amount=Decimal("200.00"),
        memo_date=date(2026, 3, 15),
    )
    memo.lines = lines
    return memo


def test_ar_credit_memo_to_sap_never_includes_base_document_fields() -> None:
    """Even when related_ar_invoice_id is set, no line-level linkage is
    attempted — see the mapper's docstring for why."""
    memo = _ar_credit_memo([_ar_credit_memo_line(1)])
    memo.related_ar_invoice_id = uuid.uuid4()

    payload = ar_credit_memo_to_sap(memo, customer_card_code="C0001")

    line = payload["DocumentLines"][0]
    assert "BaseType" not in line
    assert "BaseEntry" not in line
    assert "BaseLine" not in line
    assert payload["NumAtCard"] == "ARCM-TEST-1"


def _outgoing_payment() -> OutgoingPayment:
    payment = OutgoingPayment(
        payment_number="PMT-TEST-1",
        vendor_id=uuid.uuid4(),
        invoice_id=uuid.uuid4(),
        amount=Decimal("1000.00"),
        currency="USD",
        payment_method="bank_transfer",
        scheduled_date=date(2026, 4, 1),
    )
    return payment


def test_outgoing_payment_to_sap_maps_core_fields() -> None:
    payment = _outgoing_payment()
    payment.executed_date = date(2026, 4, 2)

    payload = outgoing_payment_to_sap(
        payment,
        vendor_card_code="V0001",
        ap_invoice_sap_doc_entry=55,
        cash_account_code="_SYS_CASH_001",
    )

    assert payload["CardCode"] == "V0001"
    assert payload["DocDate"] == "2026-04-02"  # uses executed_date when present
    assert payload["CashAccount"] == "_SYS_CASH_001"
    assert payload["CashSum"] == 1000.00
    assert payload["PaymentInvoices"] == [
        {"DocEntry": 55, "InvoiceType": "it_PurchaseInvoice", "SumApplied": 1000.00}
    ]


def test_outgoing_payment_to_sap_falls_back_to_scheduled_date() -> None:
    payment = _outgoing_payment()  # executed_date not set
    payload = outgoing_payment_to_sap(
        payment, vendor_card_code="V0001", ap_invoice_sap_doc_entry=55, cash_account_code="ACC1"
    )
    assert payload["DocDate"] == "2026-04-01"


def _incoming_payment() -> IncomingPayment:
    return IncomingPayment(
        payment_number="RCPT-TEST-1",
        customer_id=uuid.uuid4(),
        ar_invoice_id=uuid.uuid4(),
        amount=Decimal("500.00"),
        currency="USD",
        payment_method="bank_transfer",
        received_date=date(2026, 4, 5),
    )


def test_incoming_payment_to_sap_maps_core_fields() -> None:
    payment = _incoming_payment()
    payload = incoming_payment_to_sap(
        payment,
        customer_card_code="C0001",
        ar_invoice_sap_doc_entry=77,
        cash_account_code="_SYS_CASH_001",
    )

    assert payload["CardCode"] == "C0001"
    assert payload["DocDate"] == "2026-04-05"
    assert payload["CashSum"] == 500.00
    assert payload["PaymentInvoices"] == [
        {"DocEntry": 77, "InvoiceType": "it_Invoice", "SumApplied": 500.00}
    ]
