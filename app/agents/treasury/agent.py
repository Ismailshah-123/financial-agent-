"""
app.agents.treasury.agent
=============================
`TreasuryAgent`: produces a cash flow forecast and liquidity risk
assessment. Structurally different from every other agent in this
platform so far — it doesn't take a single entity ID (there's no "one
invoice" or "one payment" to screen); its input is a forecast window
(`horizon_days`, defaulting to 30, and an optional `as_of` date
defaulting to today).

SAME DESIGN CHOICE AS FraudDetectionAgent: NO LLM IN THE DECISION PATH
------------------------------------------------------------------------------
The forecast numbers and the risk level both come from
`app.services.treasury_service` — 100% deterministic. The LLM
(`_synthesize_narrative`) only turns the already-computed forecast into
readable prose; on failure, the agent falls back to a plain
deterministic summary sentence, exactly as accurate, just less
polished. A liquidity risk assessment should never silently degrade in
ACCURACY just because an LLM provider is unreachable — here, it can't.

KNOWN LIMITATION: SINGLE-CURRENCY CASH VIEW
------------------------------------------------------
`TreasuryService.get_current_cash_balance` sums ALL activity posted to
`DefaultAccounts.CASH` regardless of the currency each underlying
invoice/payment was denominated in — there's no FX conversion or
functional-currency setting anywhere in this platform yet (checked
`app.core.config`: none configured). For a company that only ever
transacts in one currency this is exactly correct; for one that
genuinely operates in several, this forecast silently treats them as
fungible, which they aren't. `financial_impact.currency` below is
labeled PKR as this platform's working default (matching the same
default used in `PeriodCloseService.close_period`), not because the
underlying balance is actually known to be in PKR.

WHAT THIS AGENT NEVER DOES
------------------------------
Purely informational — there is no state to mutate and nothing to
recommend applying. It never touches `PaymentService`,
`ARInvoiceService`, or any other service; it only reads.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.prompts.treasury_prompts import build_narrative_prompt
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
from app.services.treasury_service import CashFlowForecast, TreasuryService, assess_liquidity_risk

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
    notes="Purely informational — this agent only reads, never writes anything.",
)

DEFAULT_HORIZON_DAYS = 30


class TreasuryAgent(BaseAgent):
    agent_type = AgentType.TREASURY

    def __init__(self, session: AsyncSession, *, llm_client: LLMClient | None = None) -> None:
        super().__init__(session)
        self.treasury_service = TreasuryService(session)
        self.llm_client = llm_client or get_llm_client()

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        horizon_days = int(context.input_payload.get("horizon_days") or DEFAULT_HORIZON_DAYS)
        as_of_raw = context.input_payload.get("as_of")
        try:
            as_of = date.fromisoformat(as_of_raw) if as_of_raw else date.today()
        except ValueError as exc:
            raise AgentExecutionError(f"'as_of' must be an ISO date string: {exc}") from exc

        forecast = await self.treasury_service.forecast_cash_flow(
            as_of=as_of, horizon_days=horizon_days
        )
        severity = assess_liquidity_risk(forecast)
        narrative = await self._synthesize_narrative(forecast)

        financial_impact = None
        if forecast.lowest_balance < 0:
            financial_impact = FinancialImpact(
                amount=abs(forecast.lowest_balance),
                currency=Currency.PKR,  # see module docstring's currency caveat
                impact_type="projected_cash_shortfall",
            )

        decision = AgentDecision(
            agent_type=self.agent_type,
            summary=_build_summary(forecast, severity),
            reasoning=narrative,
            confidence=ConfidenceScore(
                value=0.85 if forecast.events else 0.6,
                method=ConfidenceMethod.RULE_BASED,
                explanation=(
                    "Forecast is deterministic given the invoices/payments in scope; "
                    "confidence reflects forecast completeness, not the math itself — "
                    "see module docstring on what counts as a forecasted event and "
                    "what's deliberately excluded."
                    if forecast.events
                    else "No inflow/outflow events found in this window — forecast is "
                    "just the starting balance held flat, which is a weaker statement "
                    "than a forecast actually built from dated events."
                ),
            ),
            supporting_evidence=[
                SupportingEvidence(document_id=event.source_id, document_type=event.source_type)
                for event in forecast.events
            ],
            relevant_policies=["treasury_liquidity_forecast_policy"],
            financial_impact=financial_impact,
            risk_level=_RISK_LEVEL_MAP[severity],
            requires_approval=severity != "low",
            rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
        )
        return [decision]

    async def _synthesize_narrative(self, forecast: CashFlowForecast) -> str:
        fallback = (
            f"Starting balance {forecast.starting_balance}, projected to reach "
            f"{forecast.ending_balance} by {forecast.as_of.isoformat()} + "
            f"{forecast.horizon_days} days. Lowest projected point: "
            f"{forecast.lowest_balance}"
            + (
                f" on {forecast.lowest_balance_date.isoformat()}."
                if forecast.lowest_balance_date
                else " (no dip below the starting balance)."
            )
        )
        if not forecast.events:
            return fallback + " No inflow or outflow events found in this window."

        system_prompt, user_prompt = build_narrative_prompt(
            starting_balance=forecast.starting_balance,
            ending_balance=forecast.ending_balance,
            lowest_balance=forecast.lowest_balance,
            lowest_balance_date=(
                forecast.lowest_balance_date.isoformat() if forecast.lowest_balance_date else None
            ),
            horizon_days=forecast.horizon_days,
            events=[
                {
                    "date": e.event_date.isoformat(),
                    "amount": str(e.amount),
                    "type": e.source_type,
                    "description": e.description,
                }
                for e in forecast.events
            ],
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None and parsed.get("narrative"):
                return str(parsed["narrative"])
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("treasury_narrative_synthesis_failed", error=str(exc))
        return fallback


def _build_summary(forecast: CashFlowForecast, severity: str) -> str:
    if severity == "low":
        return f"Cash position healthy through the next {forecast.horizon_days} days."
    return (
        f"Liquidity risk ({severity}): projected low of {forecast.lowest_balance} "
        + (
            f"on {forecast.lowest_balance_date.isoformat()}."
            if forecast.lowest_balance_date
            else "."
        )
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
