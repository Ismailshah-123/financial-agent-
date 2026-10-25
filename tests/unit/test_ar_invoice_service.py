"""
Unit tests for app.services.ar_invoice_service.compute_ar_invoice_status
— the pure function deciding an AR invoice's status from its paid/
credited totals. No DB needed; this is exactly why the logic was
extracted into a standalone function separate from
`apply_balance_change` (which does the actual persisting).
"""

from __future__ import annotations

from decimal import Decimal

from app.db.models.enums import ARInvoiceStatus
from app.services.ar_invoice_service import compute_ar_invoice_status


def test_no_payment_or_credit_keeps_current_status() -> None:
    status = compute_ar_invoice_status(
        total_amount=Decimal("1000"),
        amount_paid=Decimal("0"),
        amount_credited=Decimal("0"),
        current_status=ARInvoiceStatus.SENT,
    )
    assert status == ARInvoiceStatus.SENT


def test_partial_cash_payment_moves_to_partially_paid() -> None:
    status = compute_ar_invoice_status(
        total_amount=Decimal("1000"),
        amount_paid=Decimal("400"),
        amount_credited=Decimal("0"),
        current_status=ARInvoiceStatus.SENT,
    )
    assert status == ARInvoiceStatus.PARTIALLY_PAID


def test_partial_credit_alone_moves_to_partially_paid() -> None:
    status = compute_ar_invoice_status(
        total_amount=Decimal("1000"),
        amount_paid=Decimal("0"),
        amount_credited=Decimal("300"),
        current_status=ARInvoiceStatus.OVERDUE,
    )
    assert status == ARInvoiceStatus.PARTIALLY_PAID


def test_full_cash_payment_moves_to_paid() -> None:
    status = compute_ar_invoice_status(
        total_amount=Decimal("1000"),
        amount_paid=Decimal("1000"),
        amount_credited=Decimal("0"),
        current_status=ARInvoiceStatus.PARTIALLY_PAID,
    )
    assert status == ARInvoiceStatus.PAID


def test_combined_payment_and_credit_covering_total_moves_to_paid() -> None:
    status = compute_ar_invoice_status(
        total_amount=Decimal("1000"),
        amount_paid=Decimal("600"),
        amount_credited=Decimal("400"),
        current_status=ARInvoiceStatus.PARTIALLY_PAID,
    )
    assert status == ARInvoiceStatus.PAID


def test_overpayment_still_resolves_to_paid_not_an_error() -> None:
    status = compute_ar_invoice_status(
        total_amount=Decimal("1000"),
        amount_paid=Decimal("1000"),
        amount_credited=Decimal("50"),
        current_status=ARInvoiceStatus.PARTIALLY_PAID,
    )
    assert status == ARInvoiceStatus.PAID


def test_void_status_is_never_overridden() -> None:
    status = compute_ar_invoice_status(
        total_amount=Decimal("1000"),
        amount_paid=Decimal("1000"),
        amount_credited=Decimal("0"),
        current_status=ARInvoiceStatus.VOID,
    )
    assert status == ARInvoiceStatus.VOID
