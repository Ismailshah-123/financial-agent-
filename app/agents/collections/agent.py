"""
app.agents.collections.agent
================================
`CollectionsAgent`: the portfolio- and customer-level counterpart to
`AccountsReceivableAgent`. Read that agent's module docstring first if
you haven't — the boundary between the two is deliberate and easy to
blur:

    AccountsReceivableAgent   ONE invoice   -> is *this invoice*
                                                overdue, and is the
                                                customer over their
                                                credit limit right now?
    CollectionsAgent          ONE customer,  -> aggregating ALL of a
                              or the whole      customer's open
                              portfolio         invoices, how urgent
                                                is collecting from
                                                them, ranked against
                                                every other customer?

Nothing here recomputes a single invoice's own overdue status or risk —
that stays `AccountsReceivableAgent`'s job. This agent's entire
deterministic core (bucket assignment, aggregation, the four-signal
priority score) lives in `app.services.aging_calculations`, reached
through `app.services.aging_service.AgingService`; see those modules'
docstrings for the actual math and its documented thresholds. This
file's only jobs are: (1) turn an already-computed
`CustomerAgingSummary` into a properly-shaped `AgentDecision`, and (2)
call the LLM for a plain-language narrative and a draft follow-up
message, with a full deterministic fallback if every provider fails or
none is configured — same "the LLM narrates, it never decides"
discipline as every other agent in this platform.

TWO INVOCATION SHAPES, ONE AGENT
------------------------------------
`input_payload["customer_id"]` present -> assess exactly that customer,
return exactly one decision (the shape the Customer Detail page's "AI
Collection Assessment" panel needs).
`customer_id` absent -> portfolio-wide run: assess every customer with
an open AR balance, and return one decision per customer whose
priority is MEDIUM or higher — a LOW-priority customer is healthy AR,
not something the approval inbox needs to see. If literally no customer
is above LOW, return one clean decision documenting that, per this
codebase's "an agent that concludes nothing still returns a documented
decision" convention (see BaseAgent).

KNOWN V1 SCOPE LIMIT, STATED PLAINLY: a portfolio-wide run on a large,
badly-delinquent book could produce a lot of decisions (and therefore a
lot of approval-inbox rows) in one call — there is no cap here. Adding
one would mean picking a cutoff number with nothing to justify it yet;
better to say so than invent an arbitrary threshold. Revisit if a real
portfolio's size makes this a genuine problem.

HOW A DECISION'S `reasoning` TEXT SEPARATES FACT FROM AI
------------------------------------------------------------
`AgentDecision.reasoning` is one string, so the provenance of each part
is spelled out in labeled lines rather than blended together:

    Rule-based assessment:          always present; built only from the
                                    deterministic aging figures and the
                                    score's own reasons
    Recommended action (rule-based): always present; the fixed action
                                    for the tier (aging_calculations)
    AI-generated explanation:       present ONLY if an LLM call actually
                                    succeeded and returned one
    Draft follow-up message (...):  labeled "AI-drafted" if the LLM wrote
                                    it, "template" if it is the fixed
                                    per-tier fallback; either way it is
                                    NOT sent, only offered for a human

If no LLM is configured or every provider fails, the two AI lines simply
don't appear (no fabricated "AI" text) and the run still succeeds with
the rule-based content. A future structured field on `AgentDecision`
would be cleaner than labeled lines in one string, but that is a shared
schema change affecting every agent, so it is out of scope here.

WHAT THIS AGENT NEVER DOES
------------------------------
Purely informational, same as TreasuryAgent — there is no state to
mutate. It never writes off a receivable, never applies a credit memo,
never places a customer on credit hold, and never sends the drafted
follow-up message itself; a human decides whether and how to act on
every decision this produces.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.prompts.collections_prompts import build_collection_assessment_prompt
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
from app.services.aging_calculations import CustomerAgingSummary, customer_sort_key, expand_customer_aging_by_currency
from app.services.aging_service import AgingService

logger = get_logger(__name__)

_TIER_TO_RISK_LEVEL = {
    "low": RiskLevel.LOW,
    "medium": RiskLevel.MEDIUM,
    "high": RiskLevel.HIGH,
    "critical": RiskLevel.CRITICAL,
}

_NO_STATE_MUTATED_ROLLBACK = RollbackStrategy(
    is_reversible=True,
    compensating_action="none_required_no_state_mutated",
    notes="Purely informational — this agent only reads AR data and never "
    "writes off, credits, holds, or sends anything itself.",
)

# No "low" entry on purpose: a low-priority customer has nothing to chase,
# so no follow-up message is drafted for them at all (see
# CollectionsAgent._synthesize_assessment).
_FALLBACK_FOLLOWUP_BY_TIER = {
    "medium": (
        "Hi {name}, this is a reminder that your account shows an outstanding balance of "
        "{amount} {currency}. Please let us know when we can expect payment, or reach out if "
        "you have any questions about this balance."
    ),
    "high": (
        "Dear {name}, your account currently shows a significant overdue balance of {amount} "
        "{currency}, with the oldest invoice {days} day(s) past due. Please arrange payment as "
        "soon as possible, or contact us promptly to discuss this account."
    ),
    "critical": (
        "Dear {name}, your account is significantly past due: {amount} {currency} outstanding, "
        "with the oldest invoice {days} day(s) overdue. This account is now under formal review. "
        "Please contact us immediately to resolve this balance."
    ),
}


class CollectionsAgent(BaseAgent):
    agent_type = AgentType.COLLECTIONS

    def __init__(self, session: AsyncSession, *, llm_client: LLMClient | None = None) -> None:
        super().__init__(session)
        self.aging_service = AgingService(session)
        self.llm_client = llm_client or get_llm_client()

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        as_of_raw = context.input_payload.get("as_of")
        try:
            as_of = date.fromisoformat(as_of_raw) if as_of_raw else date.today()
        except ValueError as exc:
            raise AgentExecutionError(f"'as_of' must be an ISO date string: {exc}") from exc

        customer_id_raw = context.input_payload.get("customer_id")
        if customer_id_raw:
            customer_id = uuid.UUID(str(customer_id_raw))
            summary = await self.aging_service.get_customer_aging(customer_id, as_of=as_of)
            return [await self._build_decision(item) for item in expand_customer_aging_by_currency(summary)]

        summaries = await self.aging_service.list_all_customer_aging(as_of=as_of)
        currency_summaries = [item for summary in summaries for item in expand_customer_aging_by_currency(summary)]
        elevated = [s for s in currency_summaries if s.priority != "low"]
        if not elevated:
            return [self._build_clean_portfolio_decision(as_of=as_of, customer_count=len(summaries))]

        # Worst-first, so a reviewer scanning this run's decisions in
        # order sees the most urgent customer first. Same shared key the
        # API list uses, so both views agree on what "worst first" means.
        elevated.sort(key=customer_sort_key)
        return [await self._build_decision(s) for s in elevated]

    async def _build_decision(self, summary: CustomerAgingSummary) -> AgentDecision:
        assessment = await self._synthesize_assessment(summary)

        # See CustomerAgingSummary's docstring: LOW priority is
        # informational only (no financial_impact -> requires_approval
        # stays False via AgentDecision's own validator); MEDIUM and
        # above carry a real exposure figure, which that same validator
        # then forces into requires_approval=True — a human reviews and
        # approves the recommended collection action, same "AI never
        # transacts without approval" rule as every other agent, even
        # though nothing here is a payment.
        financial_impact = None
        if summary.priority != "low":
            try:
                impact_currency = Currency(summary.currency)
            except ValueError as exc:
                raise AgentExecutionError(
                    "Collection assessment cannot create a financial impact for an unsupported currency code. "
                    "Correct the invoice currency and retry."
                ) from exc
            if summary.total_outstanding is None:
                raise AgentExecutionError("Collection assessment requires a single-currency exposure record.")
            financial_impact = FinancialImpact(
                amount=summary.total_outstanding,
                currency=impact_currency,
                impact_type="ar_collection_exposure",
            )

        relevant_policies = ["collections_priority_policy"]
        if summary.credit_limit is not None:
            relevant_policies.append("customer_credit_limit")

        return AgentDecision(
            agent_type=self.agent_type,
            summary=_build_summary(summary),
            reasoning=_compose_reasoning(summary, assessment),
            confidence=ConfidenceScore(
                value=0.95,
                method=ConfidenceMethod.RULE_BASED,
                explanation=(
                    "Priority score is fully deterministic given the AR ledger data in "
                    "scope (see app.services.aging_calculations for the documented "
                    "point values and thresholds); confidence reflects that the scoring "
                    "itself carries no ambiguity, not any LLM judgment."
                ),
            ),
            supporting_evidence=[
                SupportingEvidence(document_id=str(summary.customer_id), document_type="customer")
            ],
            relevant_policies=relevant_policies,
            financial_impact=financial_impact,
            risk_level=_TIER_TO_RISK_LEVEL[summary.priority],
            requires_approval=summary.priority != "low",
            rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
        )

    def _build_clean_portfolio_decision(self, *, as_of: date, customer_count: int) -> AgentDecision:
        return AgentDecision(
            agent_type=self.agent_type,
            summary=(
                f"No customers above LOW collection priority as of {as_of.isoformat()} "
                f"({customer_count} customer(s) with an open AR balance reviewed)."
            ),
            reasoning=(
                "Every customer with an outstanding AR balance scored LOW collection "
                "priority — no elevated aging concentration, chronic overdue pattern, "
                "or credit-limit exposure found. See GET /api/v1/aging/customers for "
                "the full per-customer breakdown."
            ),
            confidence=ConfidenceScore(
                value=0.95,
                method=ConfidenceMethod.RULE_BASED,
                explanation="Deterministic — every customer's priority score was computed and is LOW.",
            ),
            supporting_evidence=[],
            relevant_policies=["collections_priority_policy"],
            financial_impact=None,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
            rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
        )

    async def _synthesize_assessment(self, summary: CustomerAgingSummary) -> "_Assessment":
        """Asks the LLM for a plain-language explanation and a draft
        follow-up message. Never raises and never changes any number or
        the tier: on any failure (no key configured, provider outage,
        unparseable or incomplete output) it returns `_Assessment` with
        `ai_generated=False` and the fixed per-tier template message,
        and the caller simply omits the AI-labeled line. LOW-priority
        customers skip the LLM entirely — there is nothing to explain
        or chase, so the call would be pure cost."""
        if summary.priority == "low":
            return _Assessment(explanation=None, draft_message="", ai_generated=False)

        template_message = _FALLBACK_FOLLOWUP_BY_TIER[summary.priority].format(
            name=summary.customer_name,
            amount=summary.total_outstanding,
            currency=summary.currency,
            days=summary.oldest_days_overdue,
        )
        no_ai = _Assessment(explanation=None, draft_message=template_message, ai_generated=False)

        system_prompt, user_prompt = build_collection_assessment_prompt(
            customer_name=summary.customer_name,
            priority_tier=summary.priority,
            priority_score=summary.priority_score,
            priority_reasons=summary.priority_reasons,
            recommended_action=summary.recommended_action,
            total_outstanding=summary.total_outstanding,
            currency=summary.currency,
            oldest_days_overdue=summary.oldest_days_overdue,
            bucket_totals={
                "current": summary.current_amount,
                "1-30": summary.amount_1_30,
                "31-60": summary.amount_31_60,
                "61-90": summary.amount_61_90,
                "91-120": summary.amount_91_120,
                "121+": summary.amount_121_plus,
            },
            credit_limit=summary.credit_limit,
            credit_utilization=summary.credit_utilization,
            open_invoice_count=summary.open_invoice_count,
            overdue_invoice_count=summary.overdue_invoice_count,
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("collections_assessment_llm_failed", error=str(exc))
            return no_ai

        parsed = _parse_llm_json(response.content)
        explanation = str(parsed.get("narrative") or "").strip() if parsed else ""
        if not explanation:
            logger.warning("collections_assessment_llm_unusable_output")
            return no_ai

        drafted = str(parsed.get("draft_followup_message") or "").strip()
        return _Assessment(
            explanation=explanation,
            draft_message=drafted or template_message,
            # The message is only "AI-drafted" if the model actually wrote it;
            # an explanation with no usable draft falls back to the template
            # for the message while the explanation stays AI-generated.
            ai_generated=True,
            draft_is_ai=bool(drafted),
        )


@dataclass(frozen=True)
class _Assessment:
    explanation: str | None
    draft_message: str
    ai_generated: bool
    draft_is_ai: bool = False


def _rule_based_text(summary: CustomerAgingSummary) -> str:
    facts = (
        f"{summary.customer_name}: {summary.total_outstanding} {summary.currency} outstanding "
        f"across {summary.open_invoice_count} open invoice(s), "
        f"{summary.overdue_invoice_count} overdue"
    )
    if summary.oldest_days_overdue:
        facts += f"; oldest overdue invoice is {summary.oldest_days_overdue} day(s) overdue"
    facts += (
        f". Collection priority {summary.priority.upper()} "
        f"(score {summary.priority_score}/100). Reasons: "
        + "; ".join(r.rstrip(".") for r in summary.priority_reasons)
        + "."
    )
    return facts


def _compose_reasoning(summary: CustomerAgingSummary, assessment: "_Assessment") -> str:
    lines = [
        f"Rule-based assessment: {_rule_based_text(summary)}",
        f"Recommended action (rule-based): {summary.recommended_action}",
    ]
    if assessment.ai_generated and assessment.explanation:
        lines.append(f"AI-generated explanation: {assessment.explanation}")
    if summary.priority != "low":
        label = "AI-drafted" if assessment.draft_is_ai else "template"
        lines.append(
            f"Draft follow-up message ({label}, NOT sent, for human review): "
            f"{assessment.draft_message}"
        )
    return "\n".join(lines)


def _build_summary(summary: CustomerAgingSummary) -> str:
    if summary.priority == "low":
        return f"{summary.customer_name}: account in good standing."
    return (
        f"{summary.priority.upper()} collection priority: {summary.customer_name} — "
        f"{summary.total_outstanding} {summary.currency} outstanding, oldest invoice "
        f"{summary.oldest_days_overdue} day(s) overdue."
    )


def _parse_llm_json(raw_text: str) -> dict | None:
    """Same JSON-extraction logic duplicated across every agent — see
    app.agents.accounts_payable.agent._parse_llm_json for the original
    and the reasoning for keeping it a local copy per agent package."""
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
