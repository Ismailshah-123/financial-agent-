"""
Unit tests for FBRComplianceService's pure logic: assess_compliance_risk.
Takes a plain RemittanceAssessment dataclass, no DB session.

assess_remittance() itself (which adds the account-balance query and
the remittance-repository lookup) is exercised by
tests/integration/test_compliance.py instead — same split as every
other agent's test files this session.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.fbr_compliance_service import (
    CRITICAL_OVERDUE_DAYS,
    REMITTANCE_GRACE_DAYS,
    RemittanceAssessment,
    assess_compliance_risk,
)


def _assessment(*, outstanding: str, days_since_period_end: int) -> RemittanceAssessment:
    return RemittanceAssessment(
        period_start=date(2027, 1, 1),
        period_end=date(2027, 1, 31),
        as_of=date(2027, 1, 31),
        liability_incurred=Decimal("1000"),
        amount_remitted=Decimal("1000") - Decimal(outstanding),
        outstanding_amount=Decimal(outstanding),
        days_since_period_end=days_since_period_end,
    )


def test_fully_remitted_is_low() -> None:
    assert assess_compliance_risk(_assessment(outstanding="0", days_since_period_end=50)) == "low"


def test_overpaid_is_low() -> None:
    # Negative outstanding = remitted more than incurred — not a risk.
    assessment = _assessment(outstanding="-100", days_since_period_end=50)
    assert assess_compliance_risk(assessment) == "low"


def test_outstanding_within_grace_period_is_medium() -> None:
    assessment = _assessment(outstanding="500", days_since_period_end=REMITTANCE_GRACE_DAYS - 1)
    assert assess_compliance_risk(assessment) == "medium"


def test_outstanding_exactly_at_grace_boundary_is_medium() -> None:
    assessment = _assessment(outstanding="500", days_since_period_end=REMITTANCE_GRACE_DAYS)
    assert assess_compliance_risk(assessment) == "medium"


def test_outstanding_just_past_grace_period_is_high() -> None:
    assessment = _assessment(outstanding="500", days_since_period_end=REMITTANCE_GRACE_DAYS + 1)
    assert assess_compliance_risk(assessment) == "high"


def test_outstanding_at_critical_boundary_is_high() -> None:
    assessment = _assessment(outstanding="500", days_since_period_end=CRITICAL_OVERDUE_DAYS)
    assert assess_compliance_risk(assessment) == "high"


def test_outstanding_past_critical_boundary_is_critical() -> None:
    assessment = _assessment(outstanding="500", days_since_period_end=CRITICAL_OVERDUE_DAYS + 1)
    assert assess_compliance_risk(assessment) == "critical"


def test_zero_days_since_period_end_with_outstanding_is_medium() -> None:
    # as_of is exactly period_end — nothing overdue yet, just outstanding.
    assessment = _assessment(outstanding="1000", days_since_period_end=0)
    assert assess_compliance_risk(assessment) == "medium"


def test_negative_days_since_period_end_is_medium() -> None:
    # as_of is BEFORE period_end (checking mid-period) — can't be
    # "overdue" for something not yet concluded.
    assessment = _assessment(outstanding="1000", days_since_period_end=-5)
    assert assess_compliance_risk(assessment) == "medium"
