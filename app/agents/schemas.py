"""
app.agents.schemas
===================
The data contracts every agent in the platform speaks. These exist so
that "an AI decision must include reasoning, confidence, supporting
documents, policies, financial impact, risk level, approval requirement,
and rollback strategy" (the platform's core AI requirement) is enforced
by the type system, not by convention — an agent literally cannot return
an `AgentDecision` without populating these fields.

KEY TYPES
---------
- `ConfidenceScore`: a 0-1 score plus the method that produced it, so
  "0.82" is always traceable to how it was computed (LLM self-reported
  vs. rule-based vs. ensemble).
- `SupportingEvidence`: a pointer to the document/record that backs a
  decision (not the raw content — keeps decisions lightweight and
  auditable via reference).
- `AgentDecision`: the mandatory output shape for anything an agent
  concludes. `requires_approval` and `risk_level` together drive the
  approval-workflow engine (Phase 2): CRITICAL/HIGH risk or any
  financial-transaction decision always requires approval, regardless
  of confidence — confidence affects *routing speed*, never *whether*
  approval is required, per the "AI must never transact without
  approval" rule.
- `AgentContext`: everything an agent run needs as input (actor, tenant,
  correlation id, permissions) — the analogue of a request context.
- `AgentResult`: the full envelope returned from `BaseAgent.run()`,
  wrapping one or more decisions plus execution metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.core.constants import (
    AgentType,
    ApprovalActionType,
    ApprovalStatus,
    Currency,
    RiskLevel,
)


class ConfidenceMethod(str, Enum):
    LLM_SELF_REPORTED = "llm_self_reported"
    RULE_BASED = "rule_based"
    ENSEMBLE = "ensemble"
    HISTORICAL_MATCH = "historical_match"


class ConfidenceScore(BaseModel):
    value: float = Field(ge=0.0, le=1.0)
    method: ConfidenceMethod
    explanation: str = Field(
        description="Short human-readable reason for this score, e.g. "
        "'exact match on PO number and amount' or "
        "'vendor name fuzzy-matched at 87% similarity'."
    )


class SupportingEvidence(BaseModel):
    """A reference to a document or record that backs a decision — never
    the raw document content, to keep decisions lightweight and to avoid
    duplicating data that already lives in the document store."""

    document_id: str
    document_type: str
    excerpt: str | None = Field(
        default=None,
        description="Optional short excerpt (kept brief deliberately — "
        "this is a pointer, not a copy of the source document).",
    )


class FinancialImpact(BaseModel):
    amount: Decimal
    currency: Currency
    impact_type: str = Field(
        description="e.g. 'accounts_payable_increase', 'cash_outflow', "
        "'tax_liability'"
    )


class RollbackStrategy(BaseModel):
    """Every decision that mutates financial state must declare how it
    would be undone. `is_reversible=False` decisions (e.g. a payment
    that has already settled at the bank) must route to a higher risk
    tier automatically — see `AgentDecision.model_validator` below."""

    is_reversible: bool
    compensating_action: str = Field(
        description="e.g. 'void_journal_entry', 'issue_reversing_payment', "
        "'not_reversible_manual_reconciliation_required'."
    )
    notes: str | None = None


class AgentDecision(BaseModel):
    """
    The mandatory output shape for any conclusion an agent reaches.
    An agent function that wants to act on the world returns one or more
    of these — never a bare dict, and never mutates state directly
    without one existing first.
    """

    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_type: AgentType
    summary: str = Field(description="One-sentence plain-language summary.")
    reasoning: str = Field(
        description="Full explanation of how the agent reached this "
        "conclusion — this is what a human reviewer reads before approving."
    )
    confidence: ConfidenceScore
    supporting_evidence: list[SupportingEvidence] = Field(default_factory=list)
    relevant_policies: list[str] = Field(
        default_factory=list,
        description="Policy ids/names this decision was checked against, "
        "e.g. ['spend_limit_ap_clerk_5000', 'segregation_of_duties'].",
    )
    financial_impact: FinancialImpact | None = None
    risk_level: RiskLevel
    requires_approval: bool
    rollback_strategy: RollbackStrategy
    action_type: ApprovalActionType | None = Field(
        default=None,
        description="Explicit typed command, if this decision can be safely executed after approval.",
    )
    action_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Strictly validated payload consumed by the allowlisted approval command.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _enforce_approval_rules(self) -> "AgentDecision":
        """Hard invariants, enforced regardless of what the agent's own
        logic computed — this is the code-level backstop for the
        platform rule that AI never transacts without approval."""
        if self.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            self.requires_approval = True
        if self.financial_impact is not None and self.financial_impact.amount != 0:
            self.requires_approval = True
        if self.action_type is not None:
            self.requires_approval = True
        if self.action_type is not None and not self.action_payload:
            raise ValueError("action_payload is required when action_type is set.")
        if not self.rollback_strategy.is_reversible and self.risk_level in (
            RiskLevel.LOW,
            RiskLevel.MEDIUM,
        ):
            # An irreversible action can never be classified low/medium risk.
            self.risk_level = RiskLevel.HIGH
            self.requires_approval = True
        return self


class ApprovalRequest(BaseModel):
    """Created automatically when an `AgentDecision.requires_approval`
    is True. Consumed by the approval-workflow engine (Phase 2)."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    decision: AgentDecision
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    resolved_by_id: str | None = None
    resolution_notes: str | None = None


class AgentContext(BaseModel):
    """Everything a single agent run needs as input — the agent-layer
    analogue of an HTTP request context."""

    correlation_id: str
    tenant_id: str
    actor_id: str = Field(description="User or system id that triggered this run.")
    actor_role: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(
        default_factory=dict,
        description="Short-term working memory for this run, e.g. prior "
        "turns in a conversation or intermediate tool results. Long-term "
        "memory (vendor history, past decisions) is fetched by the agent "
        "from repositories, not carried here.",
    )


class AgentExecutionStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"


class AgentResult(BaseModel):
    """Full envelope returned from `BaseAgent.run()`."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_type: AgentType
    status: AgentExecutionStatus
    decisions: list[AgentDecision] = Field(default_factory=list)
    error_message: str | None = None
    started_at: datetime
    completed_at: datetime
    duration_ms: float
