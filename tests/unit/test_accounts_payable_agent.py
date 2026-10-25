"""
Unit tests for AccountsPayableAgent._assess_risk and the JSON-parsing
helper. These test the deterministic risk rules in isolation — no DB,
no LLM call — since `_assess_risk` takes plain values/dataclasses and
returns a tuple, and `_parse_llm_json` is a pure string->dict function.

The full `_execute` workflow (DB + LLM integrated) is exercised by
integration tests once a test database is available (see
tests/integration — not yet populated in this phase, per the README's
test-pyramid note).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.agents.accounts_payable.agent import AccountsPayableAgent, _parse_llm_json
from app.core.constants import RiskLevel
from app.db.models.enums import MatchType
from app.db.models.invoice import Invoice
from app.db.models.vendor import Vendor
from app.services.matching_service import LineDiscrepancy, MatchOutcome


def _vendor(approval_limit: Decimal | None = None) -> Vendor:
    return Vendor(
        name="Acme Supplies",
        default_currency="USD",
        payment_terms_days=30,
        approval_limit=approval_limit,
    )


def _invoice(total_amount: Decimal) -> Invoice:
    return Invoice(
        invoice_number="INV-1",
        vendor_id=uuid.uuid4(),
        currency="USD",
        subtotal=total_amount,
        total_amount=total_amount,
        invoice_date=date.today(),
        due_date=date.today(),
    )


# `_execute` is an instance method but `_assess_risk` has no dependency
# on `self` state beyond nothing — instantiate without a real session
# since risk assessment never touches self.session/repositories.
def _agent() -> AccountsPayableAgent:
    return AccountsPayableAgent.__new__(AccountsPayableAgent)  # bypass __init__


def test_duplicate_found_forces_critical_risk() -> None:
    agent = _agent()
    outcome = MatchOutcome(is_matched=True, match_type=MatchType.THREE_WAY)
    risk, confidence, _ = agent._assess_risk(
        outcome=outcome,
        vendor=_vendor(),
        invoice=_invoice(Decimal("100")),
        duplicate_found=True,
        additional_risk_flagged=False,
    )
    assert risk == RiskLevel.CRITICAL


def test_failed_match_forces_high_risk() -> None:
    agent = _agent()
    outcome = MatchOutcome(
        is_matched=False,
        match_type=MatchType.THREE_WAY,
        discrepancies=[
            LineDiscrepancy(invoice_line_number=1, reason="x", expected="a", actual="b")
        ],
    )
    risk, _, _ = agent._assess_risk(
        outcome=outcome,
        vendor=_vendor(),
        invoice=_invoice(Decimal("100")),
        duplicate_found=False,
        additional_risk_flagged=False,
    )
    assert risk == RiskLevel.HIGH


def test_manual_match_forces_high_risk_even_if_marked_matched() -> None:
    agent = _agent()
    outcome = MatchOutcome(is_matched=True, match_type=MatchType.MANUAL)
    risk, _, _ = agent._assess_risk(
        outcome=outcome,
        vendor=_vendor(),
        invoice=_invoice(Decimal("100")),
        duplicate_found=False,
        additional_risk_flagged=False,
    )
    assert risk == RiskLevel.HIGH


def test_additional_llm_flagged_risk_escalates_to_high() -> None:
    agent = _agent()
    outcome = MatchOutcome(is_matched=True, match_type=MatchType.THREE_WAY)
    risk, _, _ = agent._assess_risk(
        outcome=outcome,
        vendor=_vendor(),
        invoice=_invoice(Decimal("100")),
        duplicate_found=False,
        additional_risk_flagged=True,
    )
    assert risk == RiskLevel.HIGH


def test_matched_under_threshold_is_low_risk() -> None:
    agent = _agent()
    outcome = MatchOutcome(is_matched=True, match_type=MatchType.THREE_WAY)
    risk, confidence, _ = agent._assess_risk(
        outcome=outcome,
        vendor=_vendor(approval_limit=Decimal("10000")),
        invoice=_invoice(Decimal("500")),
        duplicate_found=False,
        additional_risk_flagged=False,
    )
    assert risk == RiskLevel.LOW
    assert confidence == 0.98


def test_matched_over_threshold_is_medium_risk() -> None:
    agent = _agent()
    outcome = MatchOutcome(is_matched=True, match_type=MatchType.THREE_WAY)
    risk, _, _ = agent._assess_risk(
        outcome=outcome,
        vendor=_vendor(approval_limit=Decimal("100")),
        invoice=_invoice(Decimal("5000")),
        duplicate_found=False,
        additional_risk_flagged=False,
    )
    assert risk == RiskLevel.MEDIUM


def test_two_way_match_has_lower_base_confidence_than_three_way() -> None:
    agent = _agent()
    outcome = MatchOutcome(is_matched=True, match_type=MatchType.TWO_WAY)
    _, confidence, _ = agent._assess_risk(
        outcome=outcome,
        vendor=_vendor(approval_limit=Decimal("10000")),
        invoice=_invoice(Decimal("500")),
        duplicate_found=False,
        additional_risk_flagged=False,
    )
    assert confidence == 0.85


def test_parse_llm_json_handles_plain_json() -> None:
    result = _parse_llm_json('{"narrative": "ok", "additional_risk_flagged": false}')
    assert result == {"narrative": "ok", "additional_risk_flagged": False}


def test_parse_llm_json_strips_markdown_code_fence() -> None:
    raw = '```json\n{"narrative": "ok"}\n```'
    result = _parse_llm_json(raw)
    assert result == {"narrative": "ok"}


def test_parse_llm_json_returns_none_on_garbage() -> None:
    assert _parse_llm_json("not json at all") is None
