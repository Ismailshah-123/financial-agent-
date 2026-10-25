"""
Unit tests for BankReconciliationAgent's decision-building methods —
these take a plain BankStatementLine ORM instance (constructible
without a DB session) and MatchCandidate dataclasses, and return a
plain AgentDecision, so they're tested directly against the agent
instance (constructed with session=None — safe here since none of
these methods touch self.session/self.repository, only _execute,
_disambiguate, and _classify_unmatched do).

The full _execute workflow (DB + LLM integrated) is exercised by
tests/integration/test_bank_reconciliation.py instead — same split as
test_tax_agent.py.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.agents.bank_reconciliation.agent import BankReconciliationAgent, _parse_llm_json
from app.core.constants import RiskLevel
from app.db.models.bank_statement_line import BankStatementLine
from app.services.bank_reconciliation_service import MatchCandidate


def _agent() -> BankReconciliationAgent:
    return BankReconciliationAgent(session=None)  # type: ignore[arg-type]


def _statement_line(**overrides) -> BankStatementLine:
    defaults = dict(
        id=uuid.uuid4(),
        statement_label="Test Bank - Sept 2026",
        transaction_date=date(2026, 9, 5),
        description="Wire transfer",
        amount=Decimal("-5000.00"),
        currency="PKR",
        bank_reference="REF-001",
        is_matched=False,
    )
    defaults.update(overrides)
    return BankStatementLine(**defaults)


def _candidate(**overrides) -> MatchCandidate:
    defaults = dict(
        payment_type="outgoing",
        payment_id=uuid.uuid4(),
        payment_amount=Decimal("5000.00"),
        payment_date=date(2026, 9, 3),
        payment_reference="REF-001",
        match_reason="reference_and_amount",
        already_matched_elsewhere=False,
    )
    defaults.update(overrides)
    return MatchCandidate(**defaults)


def test_already_matched_is_low_risk_no_approval_needed() -> None:
    line = _statement_line(
        is_matched=True, matched_payment_type="outgoing", matched_payment_id=uuid.uuid4()
    )
    decision = _agent()._already_matched_decision(line)

    assert decision.risk_level == RiskLevel.LOW
    assert decision.requires_approval is False
    assert decision.financial_impact is None


def test_reference_and_amount_match_is_low_risk_high_confidence() -> None:
    line = _statement_line()
    candidate = _candidate(match_reason="reference_and_amount")
    decision = _agent()._handle_single_candidate(line, candidate)

    assert decision.risk_level == RiskLevel.LOW
    assert decision.confidence.value == 0.9
    assert decision.requires_approval is True
    assert decision.financial_impact is None


def test_amount_and_date_match_without_reference_is_medium_risk() -> None:
    line = _statement_line(bank_reference=None)
    candidate = _candidate(match_reason="amount_and_date", payment_reference=None)
    decision = _agent()._handle_single_candidate(line, candidate)

    assert decision.risk_level == RiskLevel.MEDIUM
    assert decision.confidence.value == 0.7


def test_reference_amount_mismatch_is_high_risk_with_discrepancy_impact() -> None:
    line = _statement_line(amount=Decimal("-5000.00"))
    candidate = _candidate(match_reason="reference_amount_mismatch", payment_amount=Decimal("4800.00"))
    decision = _agent()._handle_single_candidate(line, candidate)

    assert decision.risk_level == RiskLevel.HIGH
    assert decision.requires_approval is True
    assert decision.financial_impact is not None
    assert decision.financial_impact.amount == Decimal("200.00")


def test_candidate_already_matched_elsewhere_escalates_to_high_risk() -> None:
    line = _statement_line()
    candidate = _candidate(match_reason="reference_and_amount", already_matched_elsewhere=True)
    decision = _agent()._handle_single_candidate(line, candidate)

    assert decision.risk_level == RiskLevel.HIGH
    assert "already matched" in decision.reasoning.lower()


def test_positive_amount_matches_against_incoming_payment_type() -> None:
    # amount > 0 => deposit => should be matched against IncomingPayment,
    # not OutgoingPayment. This is asserted via the candidate's own
    # payment_type field (set by BankReconciliationService, not the
    # agent) — this test just confirms the agent's reasoning text
    # correctly reflects whichever payment_type the candidate carries.
    line = _statement_line(amount=Decimal("2000.00"))
    candidate = _candidate(payment_type="incoming", match_reason="reference_and_amount")
    decision = _agent()._handle_single_candidate(line, candidate)

    assert "incoming payment" in decision.reasoning.lower()
    assert "incoming_payment" in decision.supporting_evidence[1].document_type


def test_parse_llm_json_handles_plain_json() -> None:
    result = _parse_llm_json('{"selected_candidate_index": 1, "confidence": 0.8}')
    assert result == {"selected_candidate_index": 1, "confidence": 0.8}


def test_parse_llm_json_strips_markdown_code_fence() -> None:
    raw = '```json\n{"category": "bank_fee"}\n```'
    assert _parse_llm_json(raw) == {"category": "bank_fee"}


def test_parse_llm_json_returns_none_on_garbage() -> None:
    assert _parse_llm_json("not json") is None
