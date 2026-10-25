from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.api.deps import ActorContext
from app.api.v1.vendors import _vendor_response
from app.core.constants import Currency, Permission, UserRole
from app.db.models.enums import VendorStatus


def make_vendor() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Contoso Supplies",
        tax_id="TAX-123",
        email="ap@example.test",
        phone=None,
        address_line="Industrial Road",
        bank_account_iban="PK00TEST0000000000000000",
        bank_account_swift="TESTPKKA",
        default_currency=Currency.PKR,
        payment_terms_days=30,
        approval_limit=None,
        is_1099_vendor=False,
        filer_status=None,
        status=VendorStatus.ACTIVE,
        risk_rating=12,
        sap_business_partner_code=None,
    )


def make_actor(role: UserRole) -> ActorContext:
    return ActorContext(
        user_id="user-123",
        role=role,
        permissions=[Permission.VENDOR_READ],
    )


def test_general_vendor_read_does_not_disclose_bank_coordinates() -> None:
    result = _vendor_response(make_vendor(), make_actor(UserRole.VIEWER))
    assert result.name == "Contoso Supplies"
    assert result.bank_account_iban is None
    assert result.bank_account_swift is None


def test_explicit_bank_details_permission_allows_authorized_vendor_read() -> None:
    result = _vendor_response(make_vendor(), make_actor(UserRole.FINANCE_DIRECTOR))
    assert result.bank_account_iban == "PK00TEST0000000000000000"
    assert result.bank_account_swift == "TESTPKKA"
