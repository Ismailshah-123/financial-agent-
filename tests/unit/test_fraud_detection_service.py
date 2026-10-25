"""
Unit tests for FraudDetectionService's individual signal checks —
_check_vendor_status, _check_recently_modified,
_check_new_vendor_large_payment, and _check_near_approval_limit are all
synchronous and take plain Vendor/amount/date arguments (no DB touch),
so they're tested directly against a service instance constructed with
session=None. detect_signals() itself (which adds the duplicate-payment
check via a real repository query) is exercised by
tests/integration/test_fraud_detection.py instead — same split as
test_tax_agent.py and test_bank_reconciliation_agent.py.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.db.models.enums import VendorStatus
from app.db.models.vendor import Vendor
from app.services.fraud_detection_service import FraudDetectionService, FraudSignal, overall_severity


def _service() -> FraudDetectionService:
    return FraudDetectionService(session=None)  # type: ignore[arg-type]


def _vendor(**overrides) -> Vendor:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        name="Test Vendor",
        status=VendorStatus.ACTIVE.value,
        created_at=now - timedelta(days=365),
        updated_at=now - timedelta(days=365),
        approval_limit=None,
    )
    defaults.update(overrides)
    return Vendor(**defaults)


# ---- overall_severity (pure) ----


def test_overall_severity_empty_is_low() -> None:
    assert overall_severity([]) == "low"


def test_overall_severity_picks_highest() -> None:
    signals = [
        FraudSignal("a", "medium", "x"),
        FraudSignal("b", "critical", "y"),
        FraudSignal("c", "low", "z"),
    ]
    assert overall_severity(signals) == "critical"


# ---- _check_vendor_status ----


def test_blocked_vendor_is_critical() -> None:
    vendor = _vendor(status=VendorStatus.BLOCKED.value)
    signal = _service()._check_vendor_status(vendor)
    assert signal is not None
    assert signal.severity == "critical"


def test_pending_review_vendor_is_high() -> None:
    vendor = _vendor(status=VendorStatus.PENDING_REVIEW.value)
    signal = _service()._check_vendor_status(vendor)
    assert signal is not None
    assert signal.severity == "high"


def test_active_vendor_has_no_status_signal() -> None:
    vendor = _vendor(status=VendorStatus.ACTIVE.value)
    assert _service()._check_vendor_status(vendor) is None


# ---- _check_recently_modified ----


def test_never_modified_vendor_has_no_signal() -> None:
    now = datetime.now(timezone.utc)
    vendor = _vendor(created_at=now, updated_at=now)  # equal -> never edited
    signal = _service()._check_recently_modified(vendor, date.today())
    assert signal is None


def test_modified_shortly_before_payment_is_flagged() -> None:
    now = datetime.now(timezone.utc)
    vendor = _vendor(created_at=now - timedelta(days=100), updated_at=now - timedelta(days=2))
    signal = _service()._check_recently_modified(vendor, date.today())
    assert signal is not None
    assert signal.severity == "medium"
    assert "doesn't track which field changed" in signal.description


def test_modified_long_before_payment_is_not_flagged() -> None:
    now = datetime.now(timezone.utc)
    vendor = _vendor(created_at=now - timedelta(days=365), updated_at=now - timedelta(days=60))
    signal = _service()._check_recently_modified(vendor, date.today())
    assert signal is None


# ---- _check_new_vendor_large_payment ----


def test_new_vendor_payment_exceeding_own_limit_is_high() -> None:
    now = datetime.now(timezone.utc)
    vendor = _vendor(created_at=now - timedelta(days=5), approval_limit=Decimal("1000.00"))
    signal = _service()._check_new_vendor_large_payment(vendor, Decimal("5000.00"), date.today())
    assert signal is not None
    assert signal.severity == "high"


def test_new_vendor_payment_within_limit_is_medium() -> None:
    now = datetime.now(timezone.utc)
    vendor = _vendor(created_at=now - timedelta(days=5), approval_limit=Decimal("10000.00"))
    signal = _service()._check_new_vendor_large_payment(vendor, Decimal("500.00"), date.today())
    assert signal is not None
    assert signal.severity == "medium"


def test_established_vendor_has_no_new_vendor_signal() -> None:
    now = datetime.now(timezone.utc)
    vendor = _vendor(created_at=now - timedelta(days=400))
    signal = _service()._check_new_vendor_large_payment(vendor, Decimal("5000.00"), date.today())
    assert signal is None


# ---- _check_near_approval_limit ----


def test_amount_at_95_percent_of_limit_is_flagged() -> None:
    vendor = _vendor(approval_limit=Decimal("1000.00"))
    signal = _service()._check_near_approval_limit(vendor, Decimal("950.00"))
    assert signal is not None
    assert signal.severity == "medium"


def test_amount_well_under_limit_is_not_flagged() -> None:
    vendor = _vendor(approval_limit=Decimal("1000.00"))
    assert _service()._check_near_approval_limit(vendor, Decimal("500.00")) is None


def test_amount_at_or_over_limit_is_not_a_structuring_signal() -> None:
    # Exceeding the limit outright is a different concern (handled by
    # whatever approval-escalation logic already governs the invoice),
    # not "structuring to stay under it".
    vendor = _vendor(approval_limit=Decimal("1000.00"))
    assert _service()._check_near_approval_limit(vendor, Decimal("1000.00")) is None
    assert _service()._check_near_approval_limit(vendor, Decimal("1200.00")) is None


def test_no_approval_limit_configured_means_no_signal() -> None:
    vendor = _vendor(approval_limit=None)
    assert _service()._check_near_approval_limit(vendor, Decimal("999999.00")) is None
