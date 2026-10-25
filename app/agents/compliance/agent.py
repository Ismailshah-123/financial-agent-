"""
app.agents.compliance.agent
===============================
`ComplianceAgent`: FBR withholding-tax remittance compliance. Given a
period (`period_start`, `period_end`, optional `as_of`), assesses
whether the withholding tax liability incurred in that period has been
remitted, and produces a single `AgentDecision`.

Portfolio/period-scoped, not entity-scoped — same reasoning as
`TreasuryAgent`: there's no single "thing" to check for a remittance
compliance question, only a period.

Uses `AgentType.COMPLIANCE`, not `AgentType.AUDIT` — both exist as
distinct enum values (`app.core.constants.AgentType`). This agent
covers regulatory remittance compliance specifically; a separate audit
agent (forensic review of the ledger/audit trail itself) remains
unbuilt — see this codebase's project status doc for why: the audit
log (`app.core.logging.AuditLogger`) is currently in-memory/log-output
only, not persisted to a queryable table despite its own docstring
describing that as "the production implementation" — building a real
audit-integrity-verification agent needs that persistence layer first,
which is a larger, separate change than this session took on.

SAME ARCHITECTURE CHOICE AS EVERY OTHER RULE-BASED AGENT THIS SESSION:
NO LLM IN THE DECISION PATH. The liability/remittance numbers and the
risk level both come from `app.services.fbr_compliance_service` —
deterministic arithmetic and a real account-balance query, nothing an
LLM judges. The LLM (`_synthesize_narrative`) only narrates the
already-computed assessment; on failure, the agent falls back to a
plain deterministic sentence.

WHAT THIS AGENT NEVER DOES
------------------------------
Never calls `FBRComplianceService.record_remittance` — recording an
actual remittance is a direct human action via `POST
/api/v1/fbr-remittances` (see `app.api.v1.fbr_remittances`), not
something this agent creates. This agent only evaluates compliance
against remittances that already exist.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.prompts.compliance_prompts import build_narrative_prompt
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
from app.services.fbr_compliance_service import (
    FBRComplianceService,
    RemittanceAssessment,
    assess_compliance_risk,
)

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
    notes="Purely evaluative — this agent only reads, never records a remittance itself.",
)


class ComplianceAgent(BaseAgent):
    agent_type = AgentType.COMPLIANCE

    def __init__(self, session: AsyncSession, *, llm_client: LLMClient | None = None) -> None:
        super().__init__(session)
        self.compliance_service = FBRComplianceService(session)
        self.llm_client = llm_client or get_llm_client()

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        period_start_raw = context.input_payload.get("period_start")
        period_end_raw = context.input_payload.get("period_end")
        if not period_start_raw or not period_end_raw:
            raise AgentExecutionError(
                "input_payload must include 'period_start' and 'period_end'."
            )
        try:
            period_start = date.fromisoformat(period_start_raw)
            period_end = date.fromisoformat(period_end_raw)
        except ValueError as exc:
            raise AgentExecutionError(f"period_start/period_end must be ISO dates: {exc}") from exc

        as_of_raw = context.input_payload.get("as_of")
        try:
            as_of = date.fromisoformat(as_of_raw) if as_of_raw else date.today()
        except ValueError as exc:
            raise AgentExecutionError(f"'as_of' must be an ISO date string: {exc}") from exc

        assessment = await self.compliance_service.assess_remittance(
            period_start=period_start, period_end=period_end, as_of=as_of
        )
        severity = assess_compliance_risk(assessment)
        narrative = await self._synthesize_narrative(assessment)

        financial_impact = None
        if assessment.outstanding_amount > 0:
            financial_impact = FinancialImpact(
                amount=assessment.outstanding_amount,
                currency=Currency.PKR,  # withholding tax is a PKR-specific mechanism (Section 153)
                impact_type="fbr_withholding_remittance_outstanding",
            )

        decision = AgentDecision(
            agent_type=self.agent_type,
            summary=_build_summary(assessment, severity),
            reasoning=narrative,
            confidence=ConfidenceScore(
                value=0.95,
                method=ConfidenceMethod.RULE_BASED,
                explanation=(
                    "Liability and remittance amounts are exact account-balance and "
                    "recorded-remittance figures, not estimates — only the (illustrative, "
                    "unverified) grace-period assumption used to set risk_level carries "
                    "real uncertainty. See module docstring."
                ),
            ),
            supporting_evidence=[],
            relevant_policies=(
                ["fbr_withholding_remittance_policy"] if assessment.liability_incurred > 0 else []
            ),
            financial_impact=financial_impact,
            risk_level=_RISK_LEVEL_MAP[severity],
            requires_approval=severity != "low",
            rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
        )
        return [decision]

    async def _synthesize_narrative(self, assessment: RemittanceAssessment) -> str:
        fallback = (
            f"Period {assessment.period_start} to {assessment.period_end}: "
            f"{assessment.liability_incurred} withholding tax liability incurred, "
            f"{assessment.amount_remitted} remitted, {assessment.outstanding_amount} "
            f"outstanding ({assessment.days_since_period_end} days since period end)."
        )
        if assessment.liability_incurred == 0:
            return fallback + " No withholding tax activity in this period."

        system_prompt, user_prompt = build_narrative_prompt(
            period_start=assessment.period_start.isoformat(),
            period_end=assessment.period_end.isoformat(),
            liability_incurred=assessment.liability_incurred,
            amount_remitted=assessment.amount_remitted,
            outstanding_amount=assessment.outstanding_amount,
            days_since_period_end=assessment.days_since_period_end,
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None and parsed.get("narrative"):
                return str(parsed["narrative"])
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("compliance_narrative_synthesis_failed", error=str(exc))
        return fallback


def _build_summary(assessment: RemittanceAssessment, severity: str) -> str:
    if assessment.liability_incurred == 0:
        return "No withholding tax liability in this period."
    if severity == "low":
        return "Withholding tax fully remitted for this period."
    return f"{severity.capitalize()} remittance risk: {assessment.outstanding_amount} outstanding."


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
