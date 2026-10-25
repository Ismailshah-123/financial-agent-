"""
Unit tests for app.agents.schemas — specifically the invariants that
enforce "AI never transacts without approval" at the type level. These
are the highest-value tests in the whole foundation: if they pass, no
agent built on top of `BaseAgent` can silently skip human approval for
a risky or financially impactful decision.
"""

from __future__ import annotations

from decimal import Decimal

from app.agents.schemas import (
    AgentDecision,
    ConfidenceMethod,
    ConfidenceScore,
    FinancialImpact,
    RollbackStrategy,
)
from app.core.constants import AgentType, Currency, RiskLevel


def _base_decision(**overrides) -> AgentDecision:
    defaults = dict(
        agent_type=AgentType.ACCOUNTS_PAYABLE,
        summary="Test decision",
        reasoning="Because the test says so.",
        confidence=ConfidenceScore(
            value=0.9, method=ConfidenceMethod.RULE_BASED, explanation="exact match"
        ),
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        rollback_strategy=RollbackStrategy(
            is_reversible=True, compensating_action="void_journal_entry"
        ),
    )
    defaults.update(overrides)
    return AgentDecision(**defaults)


def test_high_risk_decision_always_requires_approval() -> None:
    decision = _base_decision(risk_level=RiskLevel.HIGH, requires_approval=False)
    assert decision.requires_approval is True


def test_critical_risk_decision_always_requires_approval() -> None:
    decision = _base_decision(risk_level=RiskLevel.CRITICAL, requires_approval=False)
    assert decision.requires_approval is True


def test_nonzero_financial_impact_always_requires_approval() -> None:
    decision = _base_decision(
        requires_approval=False,
        financial_impact=FinancialImpact(
            amount=Decimal("500.00"),
            currency=Currency.USD,
            impact_type="accounts_payable_increase",
        ),
    )
    assert decision.requires_approval is True


def test_zero_financial_impact_does_not_force_approval() -> None:
    decision = _base_decision(
        requires_approval=False,
        financial_impact=FinancialImpact(
            amount=Decimal("0"),
            currency=Currency.USD,
            impact_type="accounts_payable_increase",
        ),
    )
    assert decision.requires_approval is False


def test_irreversible_action_is_forced_to_high_risk_and_approval() -> None:
    decision = _base_decision(
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        rollback_strategy=RollbackStrategy(
            is_reversible=False,
            compensating_action="not_reversible_manual_reconciliation_required",
        ),
    )
    assert decision.risk_level == RiskLevel.HIGH
    assert decision.requires_approval is True


def test_low_risk_reversible_zero_impact_decision_does_not_require_approval() -> None:
    decision = _base_decision()
    assert decision.requires_approval is False
