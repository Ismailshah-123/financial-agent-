"""
Unit tests for FinanceDirectorAgent's pure helper functions: _max_risk,
_first_summary, _first_risk, _build_summary. All take plain
AgentResult/AgentDecision objects (constructible without a DB session)
or plain iterables.

The full _execute orchestration (which calls three real sub-agents via
their own .run()) is exercised by
tests/integration/test_finance_director.py instead — same split as
every other agent's test files this session, just with sub-agent
results standing in for DB-backed state.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.agents.finance_director.agent import (
    _build_summary,
    _first_risk,
    _first_summary,
    _max_risk,
)
from app.agents.schemas import (
    AgentDecision,
    AgentExecutionStatus,
    AgentResult,
    ConfidenceMethod,
    ConfidenceScore,
    RollbackStrategy,
)
from app.core.constants import AgentType, RiskLevel

_NOW = datetime.now(timezone.utc)
_NO_MUTATION = RollbackStrategy(is_reversible=True, compensating_action="none")


def _decision(risk_level: RiskLevel, summary: str = "test") -> AgentDecision:
    return AgentDecision(
        agent_type=AgentType.TREASURY,
        summary=summary,
        reasoning="test reasoning",
        confidence=ConfidenceScore(value=0.9, method=ConfidenceMethod.RULE_BASED, explanation="x"),
        supporting_evidence=[],
        relevant_policies=[],
        financial_impact=None,
        risk_level=risk_level,
        requires_approval=risk_level != RiskLevel.LOW,
        rollback_strategy=_NO_MUTATION,
    )


def _result(*, decisions: list[AgentDecision], error: str | None = None) -> AgentResult:
    return AgentResult(
        agent_type=AgentType.TREASURY,
        status=AgentExecutionStatus.FAILED if error else AgentExecutionStatus.SUCCESS,
        decisions=decisions,
        error_message=error,
        started_at=_NOW,
        completed_at=_NOW,
        duration_ms=1.0,
    )


# ---- _max_risk ----


def test_max_risk_empty_is_low() -> None:
    assert _max_risk([]) == RiskLevel.LOW


def test_max_risk_single_value() -> None:
    assert _max_risk([RiskLevel.MEDIUM]) == RiskLevel.MEDIUM


def test_max_risk_picks_highest_regardless_of_order() -> None:
    levels = [RiskLevel.MEDIUM, RiskLevel.CRITICAL, RiskLevel.LOW, RiskLevel.HIGH]
    assert _max_risk(levels) == RiskLevel.CRITICAL


def test_max_risk_all_low_is_low() -> None:
    assert _max_risk([RiskLevel.LOW, RiskLevel.LOW]) == RiskLevel.LOW


# ---- _first_summary / _first_risk ----


def test_first_summary_returns_none_for_empty_decisions() -> None:
    result = _result(decisions=[])
    assert _first_summary(result) is None
    assert _first_risk(result) is None


def test_first_summary_and_risk_from_first_decision() -> None:
    result = _result(decisions=[_decision(RiskLevel.HIGH, summary="cash is tight")])
    assert _first_summary(result) == "cash is tight"
    assert _first_risk(result) == "high"


# ---- _build_summary ----


def test_build_summary_all_checks_succeed() -> None:
    treasury = _result(decisions=[_decision(RiskLevel.LOW)])
    compliance = _result(decisions=[_decision(RiskLevel.LOW)])
    budgets = [_result(decisions=[_decision(RiskLevel.LOW)])]
    summary = _build_summary(RiskLevel.LOW, treasury, compliance, budgets)
    assert "3/3 checks completed" in summary
    assert "low" in summary


def test_build_summary_counts_failed_checks_as_not_completed() -> None:
    treasury = _result(decisions=[], error="LLM unreachable")
    compliance = _result(decisions=[_decision(RiskLevel.MEDIUM)])
    budgets: list[AgentResult] = []
    summary = _build_summary(RiskLevel.MEDIUM, treasury, compliance, budgets)
    assert "1/2 checks completed" in summary


def test_build_summary_reflects_overall_risk() -> None:
    treasury = _result(decisions=[_decision(RiskLevel.CRITICAL)])
    compliance = _result(decisions=[_decision(RiskLevel.LOW)])
    summary = _build_summary(RiskLevel.CRITICAL, treasury, compliance, [])
    assert "critical" in summary
