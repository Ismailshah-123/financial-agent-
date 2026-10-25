"""
Unit tests for SAPIntegrationAgent._build_decision — the pure-ish
decision-construction logic (given a SyncOutcome, what AgentDecision
comes out), tested with a stub LLM client so no real provider call
happens. This does not exercise `_execute` (which needs a DB session
and a live/mocked SAP client) — that's integration-test territory.
"""

from __future__ import annotations

import uuid

from app.agents.sap_integration.agent import SAPIntegrationAgent
from app.core.constants import RiskLevel
from app.services.sap_sync_service import SyncOutcome


class _StubLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubLLMClient:
    """Returns a canned response, or raises, depending on how it's
    configured — lets tests exercise both the LLM-success and the
    fallback-narrative paths deterministically."""

    def __init__(self, *, content: str | None = None, should_raise: bool = False) -> None:
        self._content = content
        self._should_raise = should_raise

    async def complete(self, *, system_prompt: str, user_prompt: str, **kwargs):
        if self._should_raise:
            raise RuntimeError("simulated LLM provider outage")
        return _StubLLMResponse(self._content or "{}")


def _agent(llm_client) -> SAPIntegrationAgent:
    agent = SAPIntegrationAgent.__new__(SAPIntegrationAgent)  # bypass __init__
    agent.llm_client = llm_client
    return agent


def _outcome(**overrides) -> SyncOutcome:
    defaults = dict(entity_type="vendor", entity_id=uuid.uuid4(), action="created")
    defaults.update(overrides)
    return SyncOutcome(**defaults)


async def test_created_outcome_is_low_risk_no_approval() -> None:
    agent = _agent(_StubLLMClient())
    decision = await agent._build_decision(_outcome(action="created", sap_card_code="V0001"))
    assert decision.risk_level == RiskLevel.LOW
    assert decision.requires_approval is False
    assert decision.financial_impact is None


async def test_no_change_outcome_is_low_risk_no_approval() -> None:
    agent = _agent(_StubLLMClient())
    decision = await agent._build_decision(
        _outcome(action="no_change", sap_card_code="V0001")
    )
    assert decision.risk_level == RiskLevel.LOW
    assert decision.requires_approval is False


async def test_conflict_outcome_is_high_risk_requires_approval() -> None:
    agent = _agent(_StubLLMClient())  # empty {} response -> falls back internally? no, {} parses fine
    outcome = _outcome(
        action="conflict",
        sap_card_code="V0001",
        conflicting_fields={"CardName": ("Acme Supplies", "Acme Supplies Inc")},
    )
    decision = await agent._build_decision(outcome)
    assert decision.risk_level == RiskLevel.HIGH
    assert decision.requires_approval is True


async def test_conflict_outcome_uses_llm_narrative_when_available() -> None:
    llm = _StubLLMClient(
        content='{"narrative": "Names differ between systems.", "suggested_investigation": "check recent edits"}'
    )
    agent = _agent(llm)
    outcome = _outcome(
        action="conflict",
        sap_card_code="V0001",
        conflicting_fields={"CardName": ("Acme Supplies", "Acme Supplies Inc")},
    )
    decision = await agent._build_decision(outcome)
    assert "Names differ between systems." in decision.reasoning
    assert "check recent edits" in decision.reasoning


async def test_conflict_outcome_falls_back_when_llm_fails() -> None:
    agent = _agent(_StubLLMClient(should_raise=True))
    outcome = _outcome(
        action="conflict",
        sap_card_code="V0001",
        conflicting_fields={"CardName": ("Acme Supplies", "Acme Supplies Inc")},
    )
    decision = await agent._build_decision(outcome)
    assert decision.risk_level == RiskLevel.HIGH  # deterministic risk unaffected by LLM outage
    assert "CardName" in decision.reasoning  # fallback narrative still names the field


async def test_failed_outcome_is_high_risk_requires_approval() -> None:
    agent = _agent(_StubLLMClient(should_raise=True))
    outcome = _outcome(action="failed", error_message="Invalid CardCode format")
    decision = await agent._build_decision(outcome)
    assert decision.risk_level == RiskLevel.HIGH
    assert decision.requires_approval is True
    assert "Invalid CardCode format" in decision.reasoning


async def test_document_created_outcome_uses_doc_entry_not_card_code() -> None:
    """Purchase orders / AP invoices sync via sap_doc_entry, not
    sap_card_code — the decision text must reference the right one."""
    agent = _agent(_StubLLMClient())
    outcome = _outcome(entity_type="purchase_order", action="created", sap_doc_entry=42)
    decision = await agent._build_decision(outcome)
    assert decision.risk_level == RiskLevel.LOW
    assert "42" in decision.reasoning


async def test_document_no_change_outcome_is_low_risk() -> None:
    agent = _agent(_StubLLMClient())
    outcome = _outcome(entity_type="ap_invoice", action="no_change", sap_doc_entry=99)
    decision = await agent._build_decision(outcome)
    assert decision.risk_level == RiskLevel.LOW
    assert decision.requires_approval is False
