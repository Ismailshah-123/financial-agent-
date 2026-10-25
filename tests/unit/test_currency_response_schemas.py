"""Pydantic response contract regressions for mixed-currency summaries."""
from datetime import date
from decimal import Decimal
import uuid

from app.schemas.aging import CustomerAgingRead, PortfolioAgingSummaryRead
from app.schemas.ap_priority import APPrioritySummaryRead, VendorExposureRead
from app.schemas.agent import RunSAPIntegrationAgentRequest
from pydantic import ValidationError
import pytest
from app.services.aging_calculations import compute_invoice_aging, summarize_customer_aging, summarize_portfolio_aging
from app.services.ap_priority_calculations import PaymentPriorityStatus, compute_payment_obligation, summarize_ap_priority, summarize_vendor_exposure


def _invoice(currency: str, amount: str, due_day: int = 1):
    return compute_invoice_aging(invoice_id=uuid.uuid4(), invoice_number=f"INV-{currency}-{amount}",
        customer_id=uuid.UUID("00000000-0000-0000-0000-000000000010"), customer_name="Currency Test",
        invoice_date=date(2026,1,1), due_date=date(2026,9,due_day), total_amount=Decimal(amount),
        amount_paid=Decimal("0"), amount_credited=Decimal("0"), currency=currency,
        status="approved", as_of=date(2026,10,1))


def test_mixed_currency_aging_schemas_have_null_flat_totals():
    rows=[_invoice("PKR","125.10"),_invoice("USD","2.30",15)]
    customer=summarize_customer_aging(customer_id=rows[0].customer_id,customer_name="Currency Test",currency="PKR",
        credit_limit=Decimal("1000"),invoices=rows,as_of=date(2026,10,1))
    portfolio=summarize_portfolio_aging(as_of=date(2026,10,1),invoices=rows)
    customer_schema=CustomerAgingRead.model_validate(customer)
    portfolio_schema=PortfolioAgingSummaryRead.model_validate(portfolio)
    assert customer_schema.total_outstanding is None and customer_schema.currency is None
    assert {b.currency:b.total_outstanding for b in customer_schema.currency_balances}=={"PKR":Decimal("125.10"),"USD":Decimal("2.30")}
    assert portfolio_schema.total_outstanding is None
    assert {b.currency:b.total_outstanding for b in portfolio_schema.currency_balances}=={"PKR":Decimal("125.10"),"USD":Decimal("2.30")}


def test_mixed_currency_ap_schemas_have_null_flat_totals():
    vendor_id=uuid.UUID("00000000-0000-0000-0000-000000000020")
    obligations=[compute_payment_obligation(invoice_id=uuid.uuid4(),invoice_number=f"AP-{ccy}",vendor_id=vendor_id,
        vendor_name="Vendor Test",amount=Decimal(amount),currency=ccy,due_date=date(2026,9,1),as_of=date(2026,10,1),
        status=PaymentPriorityStatus.READY_TO_SCHEDULE) for ccy,amount in [("PKR","500.25"),("EUR","4.15")]]
    vendor=summarize_vendor_exposure(vendor_id=vendor_id,vendor_name="Vendor Test",currency="PKR",obligations=obligations)
    summary=summarize_ap_priority(as_of=date(2026,10,1),obligations=obligations)
    vendor_schema=VendorExposureRead.model_validate(vendor)
    summary_schema=APPrioritySummaryRead.model_validate(summary)
    assert vendor_schema.total_exposure is None
    assert {b.currency:b.total_exposure for b in vendor_schema.currency_balances}=={"EUR":Decimal("4.15"),"PKR":Decimal("500.25")}
    assert summary_schema.total_payable is None
    assert {b.currency:b.total_payable for b in summary_schema.currency_balances}=={"EUR":Decimal("4.15"),"PKR":Decimal("500.25")}



def test_interactive_sap_request_rejects_financial_document_and_payment_writes():
    assert RunSAPIntegrationAgentRequest(entity_type="customer", entity_id=uuid.uuid4())
    for unsupported in ("purchase_order", "ap_invoice", "ar_invoice", "ar_credit_memo", "outgoing_payment", "incoming_payment"):
        with pytest.raises(ValidationError):
            RunSAPIntegrationAgentRequest(entity_type=unsupported, entity_id=uuid.uuid4())
