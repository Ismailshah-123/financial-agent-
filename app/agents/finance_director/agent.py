"""
app.agents.finance_director.agent
=====================================
`FinanceDirectorAgent`: orchestrates a period review across three
existing agents — `TreasuryAgent` (cash flow forecast),
`ComplianceAgent` (FBR withholding remittance), and `BudgetPlanningAgent`
(run once per budget overlapping the period) — and synthesizes their
findings into one executive-level `AgentDecision`, returned alongside
every sub-decision it collected along the way.

DIFFERENT IN KIND FROM EVERY OTHER AGENT IN THIS PLATFORM
------------------------------------------------------------------
Every other agent calls SERVICES and reasons about data directly. This
one calls OTHER AGENTS — genuine multi-agent orchestration, not just a
figure of speech. Each sub-agent is invoked through its own `.run()`
(not `._execute()` directly), so each gets its own permission check,
logging, and event-bus publication exactly as if it had been called
directly through the API — this agent doesn't shortcut any of that.

TWO KINDS OF "PERIOD" IN ONE REQUEST, DELIBERATELY NOT UNIFIED
------------------------------------------------------------------------------
`period_start`/`period_end` describes the period being REVIEWED —
what Compliance and Budget check actuals against. Treasury's forecast
is inherently forward-looking (see that agent's own module docstring),
so it's run from `as_of` with its own `horizon_days`, independent of
how long the review period is. Forcing these into the same window
would misrepresent what a cash flow forecast even means — it was never
about the past.

WHY BUDGET DISCOVERY, NOT ENTITY DISCOVERY, FOR v1
------------------------------------------------------------------
This agent discovers every `Budget` overlapping the period
(`BudgetRepository.list_all_for_period`) and runs `BudgetPlanningAgent`
on each — a tractable, well-defined query. It does NOT attempt to
discover "every invoice/payment/statement-line worth checking this
period" for Tax/Fraud/Bank Reconciliation — those agents are entity-
scoped with no existing "list what's relevant to this period" query
built for them, and building that discovery layer for three more agent
types is real, separate scope, not a natural extension of this one.
Documented here as a deliberate v1 boundary, not a silent gap — see the
project status doc for the same framing applied elsewhere this
session.

FAILURE HANDLING: PARTIAL SUCCESS IS A REAL, NAMED OUTCOME
------------------------------------------------------------------------------
`BaseAgent.run()` already catches its own exceptions and returns a
FAILED `AgentResult` rather than raising — so if Treasury fails for any
reason, Compliance and Budget still run, and the synthesis narrative
says plainly which check couldn't complete rather than the whole period
review failing because one piece did.

NO SUMMED financial_impact
------------------------------
The synthesis decision deliberately carries `financial_impact=None`.
A projected cash shortfall, an FBR remittance liability, and a budget
overrun are not the same kind of dollar and summing them would produce
a number that looks precise but means nothing real — the individual
sub-decisions (returned alongside the synthesis) carry their own,
meaningful figures.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.budget_planning.agent import BudgetPlanningAgent
from app.agents.compliance.agent import ComplianceAgent
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.prompts.finance_director_prompts import build_synthesis_prompt
from app.agents.schemas import (
    AgentContext,
    AgentDecision,
    AgentResult,
    ConfidenceMethod,
    ConfidenceScore,
    RollbackStrategy,
    SupportingEvidence,
)
from app.agents.treasury.agent import DEFAULT_HORIZON_DAYS, TreasuryAgent
from app.core.constants import AgentType, RiskLevel, UserRole
from app.core.exceptions import AgentExecutionError
from app.core.logging import get_logger
from app.repositories.budget_repository import BudgetRepository

logger = get_logger(__name__)

_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}

_NO_STATE_MUTATED_ROLLBACK = RollbackStrategy(
    is_reversible=True,
    compensating_action="none_required_no_state_mutated",
    notes=(
        "This agent only orchestrates read-only sub-agent runs and synthesizes their "
        "output — it never mutates anything itself, and neither do any of the agents "
        "it calls (Treasury, Compliance, Budget Planning are all purely evaluative)."
    ),
)


class FinanceDirectorAgent(BaseAgent):
    agent_type = AgentType.FINANCE_DIRECTOR

    def __init__(self, session: AsyncSession, *, llm_client: LLMClient | None = None) -> None:
        super().__init__(session)
        self.budget_repository = BudgetRepository(session)
        self.llm_client = llm_client or get_llm_client()
        self.treasury_agent = TreasuryAgent(session, llm_client=self.llm_client)
        self.compliance_agent = ComplianceAgent(session, llm_client=self.llm_client)
        self.budget_agent = BudgetPlanningAgent(session, llm_client=self.llm_client)

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

        treasury_horizon_days = int(
            context.input_payload.get("treasury_horizon_days") or DEFAULT_HORIZON_DAYS
        )
        actor_role = UserRole(context.actor_role)

        # --- Treasury: forward-looking from as_of, independent of the review period ---
        treasury_result = await self.treasury_agent.run(
            self._sub_context(
                context, input_payload={"as_of": as_of.isoformat(), "horizon_days": treasury_horizon_days}
            ),
            actor_role=actor_role,
        )

        # --- Compliance: backward-looking, the review period itself ---
        compliance_result = await self.compliance_agent.run(
            self._sub_context(
                context,
                input_payload={
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "as_of": as_of.isoformat(),
                },
            ),
            actor_role=actor_role,
        )

        # --- Budgets: every budget overlapping the review period ---
        budgets = await self.budget_repository.list_all_for_period(
            period_start=period_start, period_end=period_end
        )
        budget_results: list[AgentResult] = []
        for budget in budgets:
            budget_results.append(
                await self.budget_agent.run(
                    self._sub_context(
                        context, input_payload={"budget_id": str(budget.id), "as_of": as_of.isoformat()}
                    ),
                    actor_role=actor_role,
                )
            )

        all_sub_decisions: list[AgentDecision] = []
        all_sub_decisions.extend(treasury_result.decisions)
        all_sub_decisions.extend(compliance_result.decisions)
        for br in budget_results:
            all_sub_decisions.extend(br.decisions)

        overall_risk = _max_risk(d.risk_level for d in all_sub_decisions)
        narrative = await self._synthesize(
            period_start=period_start,
            period_end=period_end,
            treasury_result=treasury_result,
            compliance_result=compliance_result,
            budget_results=budget_results,
            overall_risk=overall_risk,
        )

        synthesis_decision = AgentDecision(
            agent_type=self.agent_type,
            summary=_build_summary(
                overall_risk, treasury_result, compliance_result, budget_results
            ),
            reasoning=narrative,
            confidence=ConfidenceScore(
                value=0.9,
                method=ConfidenceMethod.ENSEMBLE,
                explanation=(
                    "Synthesis of three sub-agent runs, each independently permission-"
                    "checked and logged; overall risk is the highest risk level found "
                    "among all of them (see module docstring on why financial_impact "
                    "isn't a naive sum of theirs)."
                ),
            ),
            supporting_evidence=[
                SupportingEvidence(document_id=str(b.id), document_type="budget") for b in budgets
            ],
            relevant_policies=["finance_director_period_review_policy"],
            financial_impact=None,
            risk_level=overall_risk,
            requires_approval=any(d.requires_approval for d in all_sub_decisions),
            rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
        )

        return [synthesis_decision, *all_sub_decisions]

    # ------------------------------------------------------------------
    def _sub_context(self, parent: AgentContext, *, input_payload: dict) -> AgentContext:
        """A fresh AgentContext for a sub-agent call, sharing the parent
        run's correlation_id/actor_id/actor_role (for traceability —
        logs and events from the sub-agent run show they were part of
        this Finance Director run) but with its own input_payload."""
        return AgentContext(
            correlation_id=parent.correlation_id,
            tenant_id=parent.tenant_id,
            actor_id=parent.actor_id,
            actor_role=parent.actor_role,
            input_payload=input_payload,
        )

    async def _synthesize(
        self,
        *,
        period_start: date,
        period_end: date,
        treasury_result: AgentResult,
        compliance_result: AgentResult,
        budget_results: list[AgentResult],
        overall_risk: RiskLevel,
    ) -> str:
        treasury_summary = _first_summary(treasury_result)
        compliance_summary = _first_summary(compliance_result)
        budget_summaries = [
            {"summary": _first_summary(br), "risk": _first_risk(br)} for br in budget_results
        ]

        fallback_parts = [f"Period review for {period_start} to {period_end}."]
        fallback_parts.append(
            f"Treasury: {treasury_summary or f'check failed ({treasury_result.error_message})'}."
        )
        fallback_parts.append(
            f"Compliance: {compliance_summary or f'check failed ({compliance_result.error_message})'}."
        )
        if budget_results:
            over_count = sum(
                1 for br in budget_results if _first_risk(br) in ("high", "critical")
            )
            fallback_parts.append(
                f"Budgets: {len(budget_results)} checked, {over_count} at high/critical risk."
            )
        else:
            fallback_parts.append("Budgets: none configured for this period.")
        fallback_parts.append(f"Overall risk: {overall_risk.value}.")
        fallback = " ".join(fallback_parts)

        system_prompt, user_prompt = build_synthesis_prompt(
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            treasury_summary=treasury_summary,
            treasury_risk=_first_risk(treasury_result),
            compliance_summary=compliance_summary,
            compliance_risk=_first_risk(compliance_result),
            budget_summaries=budget_summaries,
            overall_risk=overall_risk.value,
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None and parsed.get("narrative"):
                return str(parsed["narrative"])
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("finance_director_synthesis_failed", error=str(exc))
        return fallback


def _max_risk(risk_levels) -> RiskLevel:
    levels = list(risk_levels)
    if not levels:
        return RiskLevel.LOW
    return max(levels, key=lambda r: _RISK_ORDER[r])


def _first_summary(result: AgentResult) -> str | None:
    return result.decisions[0].summary if result.decisions else None


def _first_risk(result: AgentResult) -> str | None:
    return result.decisions[0].risk_level.value if result.decisions else None


def _build_summary(
    overall_risk: RiskLevel,
    treasury_result: AgentResult,
    compliance_result: AgentResult,
    budget_results: list[AgentResult],
) -> str:
    checks_run = sum(
        1 for r in (treasury_result, compliance_result, *budget_results) if r.decisions
    )
    total_checks = 2 + len(budget_results)
    return (
        f"Period review: {checks_run}/{total_checks} checks completed, "
        f"overall risk {overall_risk.value}."
    )


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
