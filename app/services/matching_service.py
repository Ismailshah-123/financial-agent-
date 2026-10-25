"""
app.services.matching_service
================================
The invoice-matching engine: given an invoice, a purchase order (if any),
and posted goods receipts, decides whether the invoice matches well
enough to recommend approval, and produces a structured
`MatchOutcome` explaining exactly why.

WHY THIS IS A SERVICE, NOT AGENT LOGIC
------------------------------------------
This is deterministic, rule-based, and fully unit-testable without any
LLM call — matching an invoice against a PO/GRPO is arithmetic and
tolerance checks, not reasoning that benefits from an LLM. Putting it
here (not inside `AccountsPayableAgent._execute`) means:
    1. It's testable in isolation with plain pytest, no mocked LLM client.
    2. The AP agent's job becomes "call this deterministic service, then
       translate the result into an `AgentDecision`" — the agent adds
       LLM-based judgment only where judgment genuinely helps (e.g.
       vendor-name fuzzy matching, anomaly narratives), not for
       arithmetic a service can just get right every time.
    3. Non-agent callers (a "recheck this invoice" admin action, a
       nightly batch reconciliation job) can call the same matching
       logic without going through the agent framework at all.

MATCH RULES (v1 — deterministic; tunable via MatchingTolerance)
-------------------------------------------------------------------
- No `purchase_order_id` on the invoice at all -> MANUAL match required.
- PO exists but has no posted goods receipt lines covering the invoiced
  lines -> TWO_WAY match: invoice lines are checked against PO lines
  only (price + quantity within tolerance).
- PO exists and has sufficient goods receipt coverage for the invoiced
  lines -> THREE_WAY match: invoice lines are checked against BOTH the
  PO line (price) and the received quantity (quantity <= received).
- Any line where quantity or price falls outside tolerance, or an
  invoice line has no corresponding PO line, is recorded as a
  `LineDiscrepancy` and the overall outcome is `is_matched=False`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from app.db.models.enums import MatchType
from app.db.models.goods_receipt import GoodsReceipt
from app.db.models.invoice import Invoice
from app.db.models.purchase_order import PurchaseOrder


@dataclass
class MatchingTolerance:
    """Configurable thresholds. In a later phase these become
    per-tenant/per-vendor policy rows instead of hardcoded defaults —
    kept as a plain dataclass now so the matching logic doesn't need to
    change shape when that happens, just where the values come from."""

    price_variance_pct: Decimal = Decimal("0.02")  # 2% price tolerance
    quantity_variance_pct: Decimal = Decimal("0.00")  # no over-billing tolerance


@dataclass
class LineDiscrepancy:
    invoice_line_number: int
    reason: str
    expected: str
    actual: str


@dataclass
class MatchOutcome:
    is_matched: bool
    match_type: MatchType
    discrepancies: list[LineDiscrepancy] = field(default_factory=list)
    matched_line_count: int = 0
    total_line_count: int = 0

    @property
    def summary(self) -> str:
        if self.is_matched:
            return (
                f"{self.match_type.value.replace('_', ' ')} match succeeded: "
                f"{self.matched_line_count}/{self.total_line_count} lines matched "
                f"within tolerance."
            )
        return (
            f"{self.match_type.value.replace('_', ' ')} match failed: "
            f"{len(self.discrepancies)} discrepancy(ies) found across "
            f"{self.total_line_count} lines."
        )


class InvoiceMatchingEngine:
    def __init__(self, tolerance: MatchingTolerance | None = None) -> None:
        self.tolerance = tolerance or MatchingTolerance()

    def match(
        self,
        *,
        invoice: Invoice,
        purchase_order: PurchaseOrder | None,
        goods_receipts: list[GoodsReceipt],
    ) -> MatchOutcome:
        if purchase_order is None:
            return MatchOutcome(
                is_matched=False,
                match_type=MatchType.MANUAL,
                total_line_count=len(invoice.lines),
                discrepancies=[
                    LineDiscrepancy(
                        invoice_line_number=line.line_number,
                        reason="no_purchase_order_on_invoice",
                        expected="a linked purchase order",
                        actual="none",
                    )
                    for line in invoice.lines
                ],
            )

        po_lines_by_id = {line.id: line for line in purchase_order.lines}
        received_qty_by_po_line: dict[uuid.UUID, Decimal] = {}
        for receipt in goods_receipts:
            for r_line in receipt.lines:
                received_qty_by_po_line[r_line.purchase_order_line_id] = (
                    received_qty_by_po_line.get(r_line.purchase_order_line_id, Decimal("0"))
                    + r_line.quantity_received
                )

        has_receipt_coverage = bool(received_qty_by_po_line)
        match_type = MatchType.THREE_WAY if has_receipt_coverage else MatchType.TWO_WAY

        discrepancies: list[LineDiscrepancy] = []
        matched_count = 0

        for inv_line in invoice.lines:
            po_line = po_lines_by_id.get(inv_line.purchase_order_line_id) if inv_line.purchase_order_line_id else None

            if po_line is None:
                discrepancies.append(
                    LineDiscrepancy(
                        invoice_line_number=inv_line.line_number,
                        reason="no_matching_po_line",
                        expected="a corresponding purchase order line",
                        actual="none",
                    )
                )
                continue

            price_ok = self._within_tolerance(
                inv_line.unit_price, po_line.unit_price, self.tolerance.price_variance_pct
            )
            if not price_ok:
                discrepancies.append(
                    LineDiscrepancy(
                        invoice_line_number=inv_line.line_number,
                        reason="price_variance_exceeded",
                        expected=str(po_line.unit_price),
                        actual=str(inv_line.unit_price),
                    )
                )
                continue

            if match_type == MatchType.THREE_WAY:
                received_qty = received_qty_by_po_line.get(po_line.id, Decimal("0"))
                if inv_line.quantity > received_qty:
                    discrepancies.append(
                        LineDiscrepancy(
                            invoice_line_number=inv_line.line_number,
                            reason="invoiced_quantity_exceeds_received",
                            expected=f"<= {received_qty}",
                            actual=str(inv_line.quantity),
                        )
                    )
                    continue
            else:
                qty_ok = self._within_tolerance(
                    inv_line.quantity,
                    po_line.quantity_ordered,
                    self.tolerance.quantity_variance_pct,
                )
                if not qty_ok:
                    discrepancies.append(
                        LineDiscrepancy(
                            invoice_line_number=inv_line.line_number,
                            reason="quantity_variance_exceeded",
                            expected=str(po_line.quantity_ordered),
                            actual=str(inv_line.quantity),
                        )
                    )
                    continue

            matched_count += 1

        return MatchOutcome(
            is_matched=len(discrepancies) == 0,
            match_type=match_type,
            discrepancies=discrepancies,
            matched_line_count=matched_count,
            total_line_count=len(invoice.lines),
        )

    @staticmethod
    def _within_tolerance(actual: Decimal, expected: Decimal, pct: Decimal) -> bool:
        if expected == 0:
            return actual == 0
        variance = abs(actual - expected) / expected
        return variance <= pct
