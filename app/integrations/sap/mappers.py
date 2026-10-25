"""
app.integrations.sap.mappers
===============================
Pure functions converting between this platform's domain data and SAP
Service Layer JSON payloads. No I/O, no session, no imports from
`app.integrations.sap.client` — these are plain dict-in/dict-out
transformations, which is what makes them directly unit-testable
(tests/unit/test_sap_mappers.py) without any mocked HTTP layer at all.

*** FIELD COVERAGE IS DELIBERATELY PARTIAL, NOT A FULL SAP SCHEMA ***
SAP's BusinessPartners/Documents objects have dozens of fields (payment
terms groups, price lists, warehouses, tax codes, multiple address
lines with different types, U_ user-defined fields per customer
installation, ...). Mapping every field SAP supports would be
speculative work against a schema this platform doesn't have a live
instance to verify against. What's mapped here covers the fields this
platform's own models actually carry today (see app.core.sap_reference
for the full document-type mapping and its verification warning) —
extend these functions field-by-field as real sync requirements emerge
against an actual customer's SAP configuration, rather than guessing at
completeness now.

CARDCODE ASSIGNMENT
----------------------
SAP Business Partners are keyed by `CardCode`, which is either
client-assigned or drawn from a numbering series configured in SAP,
depending on the customer's SAP setup. `generate_card_code()` below
produces a deterministic placeholder from the local UUID — this WILL
need to be replaced with whatever numbering convention the target SAP
instance actually expects (often a client requirement, not a technical
one) before this mapping is used against a real company database.
"""

from __future__ import annotations

from typing import Any

from app.core.sap_reference import SAPCardType
from app.db.models.customer import Customer
from app.db.models.vendor import Vendor


def generate_card_code(*, prefix: str, entity_id: Any) -> str:
    """Deterministic placeholder CardCode. See module docstring —
    replace with the target SAP instance's actual numbering convention
    before production use."""
    return f"{prefix}{str(entity_id).replace('-', '').upper()[:12]}"


# --------------------------------------------------------------------------
# Vendor <-> SAP BusinessPartner (CardType = cSupplier)
# --------------------------------------------------------------------------
def vendor_to_sap_business_partner(vendor: Vendor) -> dict[str, Any]:
    card_code = vendor.sap_business_partner_code or generate_card_code(
        prefix="V", entity_id=vendor.id
    )
    payload: dict[str, Any] = {
        "CardCode": card_code,
        "CardName": vendor.name,
        "CardType": SAPCardType.VENDOR,
        "Currency": vendor.default_currency,
    }
    if vendor.email:
        payload["EmailAddress"] = vendor.email
    if vendor.phone:
        payload["Phone1"] = vendor.phone
    if vendor.tax_id:
        payload["FederalTaxID"] = vendor.tax_id
    return payload


def sap_business_partner_to_vendor_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Maps a SAP BusinessPartner response back to a partial dict of
    this platform's Vendor field names — for pulling/reconciling SAP as
    the source of truth. Callers apply this via
    `VendorRepository.update(vendor, **fields)`, never by constructing a
    new Vendor from it (an existing local row's id/audit fields must be
    preserved)."""
    fields: dict[str, Any] = {"sap_business_partner_code": data.get("CardCode")}
    if "CardName" in data:
        fields["name"] = data["CardName"]
    if "EmailAddress" in data:
        fields["email"] = data["EmailAddress"]
    if "Phone1" in data:
        fields["phone"] = data["Phone1"]
    if "FederalTaxID" in data:
        fields["tax_id"] = data["FederalTaxID"]
    return fields


# --------------------------------------------------------------------------
# Customer <-> SAP BusinessPartner (CardType = cCustomer)
# --------------------------------------------------------------------------
def customer_to_sap_business_partner(customer: Customer) -> dict[str, Any]:
    card_code = customer.sap_business_partner_code or generate_card_code(
        prefix="C", entity_id=customer.id
    )
    payload: dict[str, Any] = {
        "CardCode": card_code,
        "CardName": customer.name,
        "CardType": SAPCardType.CUSTOMER,
        "Currency": customer.default_currency,
    }
    if customer.email:
        payload["EmailAddress"] = customer.email
    if customer.phone:
        payload["Phone1"] = customer.phone
    if customer.tax_id:
        payload["FederalTaxID"] = customer.tax_id
    if customer.credit_limit is not None:
        payload["CreditLimit"] = str(customer.credit_limit)
    return payload


def sap_business_partner_to_customer_fields(data: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {"sap_business_partner_code": data.get("CardCode")}
    if "CardName" in data:
        fields["name"] = data["CardName"]
    if "EmailAddress" in data:
        fields["email"] = data["EmailAddress"]
    if "Phone1" in data:
        fields["phone"] = data["Phone1"]
    if "FederalTaxID" in data:
        fields["tax_id"] = data["FederalTaxID"]
    if "CreditLimit" in data and data["CreditLimit"] is not None:
        fields["credit_limit"] = data["CreditLimit"]
    return fields


# --------------------------------------------------------------------------
# Discrepancy detection — used by SAPIntegrationAgent to flag conflicts
# between a local record and what SAP currently has, before overwriting
# either side.
# --------------------------------------------------------------------------
def diff_business_partner_fields(
    *, local_payload: dict[str, Any], sap_current: dict[str, Any]
) -> dict[str, tuple[Any, Any]]:
    """Returns {field: (local_value, sap_value)} for every field present
    in `local_payload` whose value differs from what SAP currently has.
    Empty dict means no conflict. `CardCode` is intentionally excluded —
    it's the join key, not a comparable attribute."""
    diffs: dict[str, tuple[Any, Any]] = {}
    for field, local_value in local_payload.items():
        if field == "CardCode":
            continue
        sap_value = sap_current.get(field)
        if sap_value is not None and str(local_value) != str(sap_value):
            diffs[field] = (local_value, sap_value)
    return diffs
