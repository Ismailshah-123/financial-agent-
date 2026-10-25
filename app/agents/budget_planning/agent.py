"""
app.agents.budget_planning.agent
====================================
`BudgetPlanningAgent`: given one `Budget`, computes its pace-adjusted
variance and produces a single `AgentDecision` — same one-entity-in
shape as TaxAgent/BankReconciliationAgent/FraudDetectionAgent (unlike
TreasuryAgent, which is portfolio-wide by necessity — a budget is a
specific, individual thing to check, so there's no reason to break
from the more common pattern here).

SAME ARCHITECTURE CHOICE AS FraudDetectionAgent AND TreasuryAgent:
NO LLM IN THE DECISION PATH. The variance ratio and risk level both
come from `app.services.budget_service` — deterministic arithmetic.
The LLM (`_synthesize_narrative`) only narrates the already-computed
result; on failure, the agent falls back to a plain deterministic
sentence, exactly as accurate, just less polished.

CONFIDENCE SCALES WITH elapsed_fraction, NOT JUST FIXED
------------------------------------------------------------------
Unlike the other rule-based agents (which report a fixed confidence
for a deterministic finding), this one's confidence value is
DELIBERATELY lower early in a budget period and rises toward 1.0 as
the period concludes — see `BudgetService`'s module docstring on why a
pace-based projection early in a period is a genuinely noisier signal
(one-time or front-loaded costs can make a budget look off-pace in
week one even when the full period will be fine) than the same
computation run in the period's final days, where it's converged into
essentially "did we go over."

WHAT THIS AGENT NEVER DOES
------------------------------
Never creates, edits, or approves a `Budget` — that's a direct,
human-driven planning action via `POST /api/v1/budgets` (see
`app.api.v1.budgets`), not something this agent recommends into
existence. This agent only evaluates a budget that already exists.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.prompts.budget_prompts import build_narrative_prompt
from app.agents.schemas import (
    AgentContext,
    AgentDecision,
    ConfidenceMethod,
    ConfidenceScore,
    FinancialImpact,
    RollbackStrategy,
    SupportingEvidence,
)
from app.core.constants import AgentType, Currency, RiskLevel
from app.core.exceptions import AgentExecutionError
from app.core.logging import get_logger
from app.repositories.budget_repository import BudgetRepository
from app.services.budget_service import BudgetService, BudgetVariance, assess_variance_risk

logger = get_logger(__name__)

_RISK_LEVEL_MAP = {
    "low": RiskLevel.LOW,
    "medium": RiskLevel.MEDIUM,
    "high": RiskLevel.HIGH,
    "critical": RiskLevel.CRITICAL,
}

_NO_STATE_MUTATED_ROLLBACK = RollbackStrategy(
    is_reversible=True,
    compensating_action="none_required_no_state_mutated",
    notes="Purely evaluative — this agent only reads a Budget, never creates or modifies one.",
)

# Confidence floor/ceiling for the elapsed_fraction-scaled value below —
# never fully 0 (the arithmetic itself is still sound even on day one)
# and never above 0.95 for a rule-based, LLM-independent finding (kept
# consistent with the ceiling other agents use for their most confident
# deterministic case).
_MIN_CONFIDENCE = 0.4
_MAX_CONFIDENCE = 0.95


class BudgetPlanningAgent(BaseAgent):
    agent_type = AgentType.BUDGET_PLANNING

    def __init__(self, session: AsyncSession, *, llm_client: LLMClient | None = None) -> None:
        super().__init__(session)
        self.budget_repository = BudgetRepository(session)
        self.budget_service = BudgetService(session)
        self.llm_client = llm_client or get_llm_client()

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        budget_id_raw = context.input_payload.get("budget_id")
        if not budget_id_raw:
            raise AgentExecutionError("input_payload must include 'budget_id'.")
        budget_id = uuid.UUID(str(budget_id_raw))

        as_of_raw = context.input_payload.get("as_of")
        try:
            as_of = date.fromisoformat(as_of_raw) if as_of_raw else date.today()
        except ValueError as exc:
            raise AgentExecutionError(f"'as_of' must be an ISO date string: {exc}") from exc

        budget = await self.budget_repository.get_by_id(budget_id)
        if budget is None:
            raise AgentExecutionError(f"Budget {budget_id} not found.")

        variance = await self.budget_service.compute_variance(budget, as_of=as_of)
        severity = assess_variance_risk(variance)
        narrative = await self._synthesize_narrative(variance)

        financial_impact = None
        if severity in ("high", "critical"):
            unfavorable_amount = abs(
                variance.variance_ratio * budget.budgeted_amount
            ).quantize(Decimal("0.01"))
            financial_impact = FinancialImpact(
                amount=unfavorable_amount,
                currency=Currency(budget.currency),
                impact_type="budget_variance_unfavorable",
            )

        confidence_value = _MIN_CONFIDENCE + (
            (_MAX_CONFIDENCE - _MIN_CONFIDENCE) * float(variance.elapsed_fraction)
        )

        decision = AgentDecision(
            agent_type=self.agent_type,
            summary=_build_summary(budget, variance, severity),
            reasoning=narrative,
            confidence=ConfidenceScore(
                value=round(confidence_value, 2),
                method=ConfidenceMethod.RULE_BASED,
                explanation=(
                    f"Deterministic pace-based variance; confidence rises toward "
                    f"{_MAX_CONFIDENCE} as the period concludes (currently "
                    f"{variance.elapsed_fraction:.0%} elapsed) — see module docstring "
                    f"on why an early-period pace signal is noisier."
                ),
            ),
            supporting_evidence=[
                SupportingEvidence(document_id=str(budget.id), document_type="budget")
            ],
            relevant_policies=["budget_variance_policy"] if variance.is_meaningful else [],
            financial_impact=financial_impact,
            risk_level=_RISK_LEVEL_MAP[severity],
            requires_approval=severity in ("high", "critical"),
            rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
        )
        return [decision]

    async def _synthesize_narrative(self, variance: BudgetVariance) -> str:
        budget = variance.budget
        if not variance.is_meaningful:
            return (
                f"Account '{budget.account_code}' is a {variance.account_type} account — "
                f"budget variance tracking isn't meaningful for this account type "
                f"(only EXPENSE and REVENUE accounts are supported)."
            )

        fallback = (
            f"{budget.name}: {variance.actual_amount} actual vs. {variance.expected_amount_at_pace} "
            f"expected at this point ({variance.elapsed_fraction:.0%} through the period, "
            f"target {budget.budgeted_amount}). Variance ratio: {variance.variance_ratio:.1%}."
        )

        system_prompt, user_prompt = build_narrative_prompt(
            budget_name=budget.name,
            account_code=budget.account_code,
            account_type=variance.account_type,
            budgeted_amount=budget.budgeted_amount,
            actual_amount=variance.actual_amount,
            elapsed_fraction=variance.elapsed_fraction,
            expected_amount_at_pace=variance.expected_amount_at_pace,
            variance_ratio=variance.variance_ratio,
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None and parsed.get("narrative"):
                return str(parsed["narrative"])
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("budget_narrative_synthesis_failed", error=str(exc))
        return fallback


def _build_summary(budget, variance: BudgetVariance, severity: str) -> str:
    if not variance.is_meaningful:
        return f"Not applicable — '{budget.account_code}' isn't an expense or revenue account."
    if severity == "low":
        return f"{budget.name}: on track."
    return f"{budget.name}: {severity} variance risk ({variance.variance_ratio:.0%} unfavorable vs. pace)."


def _parse_llm_json(raw_text: str) -> dict | None:
    """Identical logic to app.agents.accounts_payable.agent._parse_llm_json
    (local copy per this codebase's existing per-agent convention)."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None
