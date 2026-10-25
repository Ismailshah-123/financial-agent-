"""
Unit tests for app.integrations.sap.mappers — pure dict-in/dict-out
functions, no I/O, no mocking needed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.core.sap_reference import SAPCardType
from app.db.models.customer import Customer
from app.db.models.vendor import Vendor
from app.integrations.sap.mappers import (
    customer_to_sap_business_partner,
    diff_business_partner_fields,
    generate_card_code,
    sap_business_partner_to_customer_fields,
    sap_business_partner_to_vendor_fields,
    vendor_to_sap_business_partner,
)


def _vendor(**overrides) -> Vendor:
    defaults = dict(
        name="Acme Supplies",
        default_currency="USD",
        payment_terms_days=30,
        email="ap@acme.example",
        phone="+1-555-0100",
        tax_id="TAX-123",
    )
    defaults.update(overrides)
    vendor = Vendor(**defaults)
    vendor.id = uuid.uuid4()
    return vendor


def _customer(**overrides) -> Customer:
    defaults = dict(
        name="Globex Corp",
        default_currency="USD",
        payment_terms_days=30,
        email="ar@globex.example",
    )
    defaults.update(overrides)
    customer = Customer(**defaults)
    customer.id = uuid.uuid4()
    return customer


def test_generate_card_code_is_deterministic_for_same_id() -> None:
    entity_id = uuid.uuid4()
    assert generate_card_code(prefix="V", entity_id=entity_id) == generate_card_code(
        prefix="V", entity_id=entity_id
    )


def test_vendor_to_sap_business_partner_maps_core_fields() -> None:
    vendor = _vendor()
    payload = vendor_to_sap_business_partner(vendor)
    assert payload["CardName"] == "Acme Supplies"
    assert payload["CardType"] == SAPCardType.VENDOR
    assert payload["Currency"] == "USD"
    assert payload["EmailAddress"] == "ap@acme.example"
    assert payload["FederalTaxID"] == "TAX-123"
    assert payload["CardCode"]  # generated placeholder, non-empty


def test_vendor_to_sap_business_partner_reuses_existing_card_code() -> None:
    vendor = _vendor(sap_business_partner_code="V0009999")
    payload = vendor_to_sap_business_partner(vendor)
    assert payload["CardCode"] == "V0009999"


def test_customer_to_sap_business_partner_includes_credit_limit() -> None:
    customer = _customer(credit_limit=Decimal("15000.00"))
    payload = customer_to_sap_business_partner(customer)
    assert payload["CardType"] == SAPCardType.CUSTOMER
    assert payload["CreditLimit"] == "15000.00"


def test_customer_to_sap_business_partner_omits_credit_limit_when_none() -> None:
    customer = _customer(credit_limit=None)
    payload = customer_to_sap_business_partner(customer)
    assert "CreditLimit" not in payload


def test_sap_business_partner_to_vendor_fields_round_trip() -> None:
    sap_data = {
        "CardCode": "V0001234",
        "CardName": "Updated Name",
        "EmailAddress": "new@acme.example",
        "Phone1": "+1-555-9999",
        "FederalTaxID": "TAX-999",
    }
    fields = sap_business_partner_to_vendor_fields(sap_data)
    assert fields == {
        "sap_business_partner_code": "V0001234",
        "name": "Updated Name",
        "email": "new@acme.example",
        "phone": "+1-555-9999",
        "tax_id": "TAX-999",
    }


def test_sap_business_partner_to_customer_fields_round_trip() -> None:
    sap_data = {"CardCode": "C0005678", "CardName": "Updated Corp", "CreditLimit": "20000.00"}
    fields = sap_business_partner_to_customer_fields(sap_data)
    assert fields["sap_business_partner_code"] == "C0005678"
    assert fields["name"] == "Updated Corp"
    assert fields["credit_limit"] == "20000.00"


def test_diff_business_partner_fields_detects_mismatch() -> None:
    local = {"CardCode": "V0001", "CardName": "Acme Supplies", "EmailAddress": "a@acme.example"}
    sap_current = {
        "CardCode": "V0001",
        "CardName": "Acme Supplies Inc",
        "EmailAddress": "a@acme.example",
    }
    diffs = diff_business_partner_fields(local_payload=local, sap_current=sap_current)
    assert "CardName" in diffs
    assert diffs["CardName"] == ("Acme Supplies", "Acme Supplies Inc")
    assert "EmailAddress" not in diffs
    assert "CardCode" not in diffs  # join key, never compared


def test_diff_business_partner_fields_no_conflict_when_identical() -> None:
    local = {"CardCode": "V0001", "CardName": "Acme Supplies"}
    sap_current = {"CardCode": "V0001", "CardName": "Acme Supplies"}
    diffs = diff_business_partner_fields(local_payload=local, sap_current=sap_current)
    assert diffs == {}


def test_diff_business_partner_fields_ignores_fields_sap_does_not_have() -> None:
    """A field present locally but absent (None) on the SAP side is not
    treated as a conflict — it just hasn't been set in SAP yet, which
    is a create/first-sync scenario, not a disagreement."""
    local = {"CardCode": "V0001", "CardName": "Acme Supplies", "FederalTaxID": "TAX-1"}
    sap_current = {"CardCode": "V0001", "CardName": "Acme Supplies", "FederalTaxID": None}
    diffs = diff_business_partner_fields(local_payload=local, sap_current=sap_current)
    assert diffs == {}
