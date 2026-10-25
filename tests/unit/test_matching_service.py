"""
Unit tests for app.services.matching_service.InvoiceMatchingEngine.
Pure unit tests — no database, no async — since matching is deterministic
arithmetic against in-memory ORM instances (never persisted in these
tests, just constructed and passed straight to the engine).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models.enums import MatchType
from app.db.models.goods_receipt import GoodsReceipt, GoodsReceiptLine
from app.db.models.invoice import Invoice, InvoiceLine
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.services.matching_service import InvoiceMatchingEngine, MatchingTolerance


def _po_line(line_number=1, qty=Decimal("10"), price=Decimal("100.00")) -> PurchaseOrderLine:
    line = PurchaseOrderLine(
        line_number=line_number,
        description="Widget",
        quantity_ordered=qty,
        unit_price=price,
        line_total=qty * price,
    )
    line.id = uuid.uuid4()
    return line


def _po(lines: list[PurchaseOrderLine]) -> PurchaseOrder:
    po = PurchaseOrder(
        po_number="PO-TEST-1",
        vendor_id=uuid.uuid4(),
        currency="USD",
        total_amount=sum((l.line_total for l in lines), Decimal("0")),
        order_date=date.today(),
    )
    po.lines = lines
    return po


def _invoice_line(po_line: PurchaseOrderLine, qty: Decimal, price: Decimal, line_number=1) -> InvoiceLine:
    return InvoiceLine(
        line_number=line_number,
        purchase_order_line_id=po_line.id,
        description="Widget",
        quantity=qty,
        unit_price=price,
        line_total=qty * price,
    )


def _invoice(lines: list[InvoiceLine], po_id: uuid.UUID | None) -> Invoice:
    inv = Invoice(
        invoice_number="INV-TEST-1",
        vendor_id=uuid.uuid4(),
        purchase_order_id=po_id,
        currency="USD",
        subtotal=sum((l.line_total for l in lines), Decimal("0")),
        total_amount=sum((l.line_total for l in lines), Decimal("0")),
        invoice_date=date.today(),
        due_date=date.today(),
    )
    inv.lines = lines
    return inv


def _grpo(po: PurchaseOrder, po_line: PurchaseOrderLine, qty_received: Decimal) -> GoodsReceipt:
    grpo = GoodsReceipt(
        grpo_number="GRPO-TEST-1",
        purchase_order_id=po.id,
        received_date=date.today(),
    )
    grpo.lines = [
        GoodsReceiptLine(purchase_order_line_id=po_line.id, quantity_received=qty_received)
    ]
    return grpo


def test_no_purchase_order_forces_manual_match() -> None:
    inv_line = InvoiceLine(
        line_number=1, description="Misc", quantity=Decimal("1"),
        unit_price=Decimal("50"), line_total=Decimal("50"),
    )
    invoice = _invoice([inv_line], po_id=None)

    outcome = InvoiceMatchingEngine().match(
        invoice=invoice, purchase_order=None, goods_receipts=[]
    )

    assert outcome.match_type == MatchType.MANUAL
    assert outcome.is_matched is False
    assert len(outcome.discrepancies) == 1


def test_three_way_match_succeeds_when_price_qty_and_receipt_align() -> None:
    po_line = _po_line(qty=Decimal("10"), price=Decimal("100.00"))
    po = _po([po_line])
    grpo = _grpo(po, po_line, qty_received=Decimal("10"))
    inv_line = _invoice_line(po_line, qty=Decimal("10"), price=Decimal("100.00"))
    invoice = _invoice([inv_line], po_id=po.id)

    outcome = InvoiceMatchingEngine().match(
        invoice=invoice, purchase_order=po, goods_receipts=[grpo]
    )

    assert outcome.match_type == MatchType.THREE_WAY
    assert outcome.is_matched is True
    assert outcome.matched_line_count == 1


def test_three_way_match_fails_when_invoiced_qty_exceeds_received() -> None:
    po_line = _po_line(qty=Decimal("10"), price=Decimal("100.00"))
    po = _po([po_line])
    grpo = _grpo(po, po_line, qty_received=Decimal("5"))  # only 5 received
    inv_line = _invoice_line(po_line, qty=Decimal("10"), price=Decimal("100.00"))  # billed for 10
    invoice = _invoice([inv_line], po_id=po.id)

    outcome = InvoiceMatchingEngine().match(
        invoice=invoice, purchase_order=po, goods_receipts=[grpo]
    )

    assert outcome.is_matched is False
    assert outcome.discrepancies[0].reason == "invoiced_quantity_exceeds_received"


def test_two_way_match_used_when_no_goods_receipt_posted() -> None:
    po_line = _po_line(qty=Decimal("10"), price=Decimal("100.00"))
    po = _po([po_line])
    inv_line = _invoice_line(po_line, qty=Decimal("10"), price=Decimal("100.00"))
    invoice = _invoice([inv_line], po_id=po.id)

    outcome = InvoiceMatchingEngine().match(
        invoice=invoice, purchase_order=po, goods_receipts=[]
    )

    assert outcome.match_type == MatchType.TWO_WAY
    assert outcome.is_matched is True


def test_price_variance_within_tolerance_still_matches() -> None:
    po_line = _po_line(qty=Decimal("10"), price=Decimal("100.00"))
    po = _po([po_line])
    grpo = _grpo(po, po_line, qty_received=Decimal("10"))
    # 1% over — within the default 2% tolerance
    inv_line = _invoice_line(po_line, qty=Decimal("10"), price=Decimal("101.00"))
    invoice = _invoice([inv_line], po_id=po.id)

    outcome = InvoiceMatchingEngine().match(
        invoice=invoice, purchase_order=po, goods_receipts=[grpo]
    )

    assert outcome.is_matched is True


def test_price_variance_beyond_tolerance_fails() -> None:
    po_line = _po_line(qty=Decimal("10"), price=Decimal("100.00"))
    po = _po([po_line])
    grpo = _grpo(po, po_line, qty_received=Decimal("10"))
    # 10% over — beyond the default 2% tolerance
    inv_line = _invoice_line(po_line, qty=Decimal("10"), price=Decimal("110.00"))
    invoice = _invoice([inv_line], po_id=po.id)

    outcome = InvoiceMatchingEngine().match(
        invoice=invoice, purchase_order=po, goods_receipts=[grpo]
    )

    assert outcome.is_matched is False
    assert outcome.discrepancies[0].reason == "price_variance_exceeded"


def test_custom_tolerance_is_respected() -> None:
    po_line = _po_line(qty=Decimal("10"), price=Decimal("100.00"))
    po = _po([po_line])
    grpo = _grpo(po, po_line, qty_received=Decimal("10"))
    inv_line = _invoice_line(po_line, qty=Decimal("10"), price=Decimal("105.00"))
    invoice = _invoice([inv_line], po_id=po.id)

    strict_engine = InvoiceMatchingEngine(
        tolerance=MatchingTolerance(price_variance_pct=Decimal("0.01"))
    )
    outcome = strict_engine.match(invoice=invoice, purchase_order=po, goods_receipts=[grpo])

    assert outcome.is_matched is False
