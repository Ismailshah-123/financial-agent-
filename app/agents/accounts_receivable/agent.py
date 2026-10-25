"""
app.agents.accounts_receivable.agent
=======================================
`AccountsReceivableAgent`: given an AR invoice, assesses two things —
how overdue it is (collection risk) and whether the customer's total
outstanding balance is approaching or exceeding their credit limit
(credit exposure) — and produces one `AgentDecision` recommending a
next action. Built on the same `BaseAgent` contract as
`AccountsPayableAgent`; read that file's docstring first if this is
your first time in the agent layer, since the shared mechanics
(permission gating, failure containment, approval gating via
`AgentDecision`'s own validators) aren't re-explained here.

WORKFLOW (`_execute`)
------------------------
1. Load the AR invoice and its customer.
2. Compute days overdue (0 if not overdue) and the customer's total
   outstanding balance across all their open AR invoices
   (`ARInvoiceRepository.sum_outstanding_for_customer` — already
   includes this invoice if it's counted as open).
3. If newly overdue, mark the invoice OVERDUE via `ARInvoiceService`
   (a pure status annotation — no financial mutation, so it doesn't
   need its own approval gate; see that service's docstring).
4. LLM-assisted narrative: turn the deterministic facts into a
   plain-language explanation and a recommended next action. Same
   graceful-degradation contract as the AP agent — if every LLM
   provider fails, falls back to a deterministic narrative instead of
   failing the run.
5. Deterministic risk assessment (`_assess_risk`) combining days-overdue
   severity and credit-limit exposure. The LLM never decides risk level
   on its own, same discipline as the AP agent.

WHAT THIS AGENT NEVER DOES
------------------------------
It never writes off a receivable, never applies a credit memo, and
never places a customer on credit hold — those are consequences a human
decides on after reading this agent's recommendation, per the
platform's "AI never transacts without approval" rule. This agent's job
ends at producing the assessment.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.prompts.accounts_receivable_prompts import build_collection_risk_prompt
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
from app.db.models.ar_invoice import ARInvoice
from app.db.models.customer import Customer
from app.repositories.ar_invoice_repository import ARInvoiceRepository
from app.repositories.customer_repository import CustomerRepository
from app.services.ar_invoice_service import ARInvoiceService

logger = get_logger(__name__)


class AccountsReceivableAgent(BaseAgent):
    agent_type = AgentType.ACCOUNTS_RECEIVABLE

    def __init__(self, session: AsyncSession, *, llm_client: LLMClient | None = None) -> None:
        super().__init__(session)
        self.ar_invoice_repository = ARInvoiceRepository(session)
        self.customer_repository = CustomerRepository(session)
        self.ar_invoice_service = ARInvoiceService(session)
        self.llm_client = llm_client or get_llm_client()

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        invoice_id_raw = context.input_payload.get("ar_invoice_id")
        if not invoice_id_raw:
            raise AgentExecutionError("input_payload must include 'ar_invoice_id'.")
        invoice_id = uuid.UUID(str(invoice_id_raw))

        invoice = await self.ar_invoice_repository.get_by_id_with_lines(invoice_id)
        if invoice is None:
            raise AgentExecutionError(f"AR invoice {invoice_id} not found.")
        customer = await self.customer_repository.get_by_id_or_raise(invoice.customer_id)

        # --- Step 2: deterministic facts ---
        days_overdue = max(0, (date.today() - invoice.due_date).days)
        customer_total_outstanding = (
            await self.ar_invoice_repository.sum_outstanding_for_customer(customer.id)
        )

        # --- Step 3: mark overdue if applicable (pure status update) ---
        if days_overdue > 0:
            invoice = await self.ar_invoice_service.mark_overdue(
                invoice, actor_id=context.actor_id
            )

        # --- Step 4: LLM narrative (best-effort) ---
        narrative, recommended_action, additional_concern = await self._get_narrative(
            invoice=invoice,
            customer=customer,
            days_overdue=days_overdue,
            customer_total_outstanding=customer_total_outstanding,
        )

        # --- Step 5: deterministic risk assessment ---
        risk_level, confidence_value, confidence_explanation = self._assess_risk(
            customer=customer,
            days_overdue=days_overdue,
            customer_total_outstanding=customer_total_outstanding,
        )

        reasoning_parts = [narrative]
        if recommended_action:
            reasoning_parts.append(f"Recommended action: {recommended_action}.")
        if additional_concern:
            reasoning_parts.append(f"Additional concern: {additional_concern}")
        reasoning = " ".join(part for part in reasoning_parts if part)

        supporting_evidence = [
            SupportingEvidence(document_id=str(invoice.id), document_type="ar_invoice"),
            SupportingEvidence(document_id=str(customer.id), document_type="customer"),
        ]

        relevant_policies = ["collections_policy"]
        if customer.credit_limit is not None:
            relevant_policies.append("customer_credit_limit")

        decision = AgentDecision(
            agent_type=self.agent_type,
            summary=self._summary(days_overdue, customer, customer_total_outstanding),
            reasoning=reasoning,
            confidence=ConfidenceScore(
                value=confidence_value,
                method=ConfidenceMethod.ENSEMBLE,
                explanation=confidence_explanation,
            ),
            supporting_evidence=supporting_evidence,
            relevant_policies=relevant_policies,
            financial_impact=FinancialImpact(
                amount=invoice.amount_outstanding,
                currency=Currency(invoice.currency),
                impact_type="accounts_receivable_collection_risk",
            ),
            risk_level=risk_level,
            requires_approval=risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL),
            rollback_strategy=RollbackStrategy(
                is_reversible=True,
                compensating_action="no_financial_mutation_assessment_only",
                notes=(
                    "This decision only assesses risk and recommends an action; "
                    "it does not itself write off, credit, or otherwise mutate "
                    "the receivable. Nothing here requires rollback."
                ),
            ),
        )
        return [decision]

    def _summary(
        self, days_overdue: int, customer: Customer, customer_total_outstanding: Decimal
    ) -> str:
        if days_overdue <= 0:
            return f"Invoice not yet overdue. {customer.name} total outstanding: {customer_total_outstanding}."
        return (
            f"Invoice {days_overdue} day(s) overdue. {customer.name} total "
            f"outstanding: {customer_total_outstanding}."
        )

    async def _get_narrative(
        self,
        *,
        invoice: ARInvoice,
        customer: Customer,
        days_overdue: int,
        customer_total_outstanding: Decimal,
    ) -> tuple[str, str, str]:
        system_prompt, user_prompt = build_collection_risk_prompt(
            invoice=invoice,
            customer=customer,
            days_overdue=days_overdue,
            customer_total_outstanding=customer_total_outstanding,
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None:
                return (
                    str(parsed.get("narrative", "")),
                    str(parsed.get("recommended_action", "")),
                    str(parsed.get("additional_concern", "")),
                )
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("ar_agent_llm_narrative_failed", error=str(exc))

        # Deterministic fallback narrative.
        if days_overdue <= 0:
            fallback = (
                f"Invoice {invoice.invoice_number} is not yet overdue "
                f"(due {invoice.due_date.isoformat()})."
            )
            action = "no action required"
        elif days_overdue <= 30:
            fallback = (
                f"Invoice {invoice.invoice_number} is {days_overdue} day(s) overdue."
            )
            action = "send a payment reminder"
        elif days_overdue <= 60:
            fallback = (
                f"Invoice {invoice.invoice_number} is {days_overdue} day(s) overdue — "
                f"beyond normal terms."
            )
            action = "escalate to a formal collections follow-up"
        else:
            fallback = (
                f"Invoice {invoice.invoice_number} is {days_overdue} day(s) overdue — "
                f"significantly delinquent."
            )
            action = "escalate to collections and consider a credit hold"
        return fallback, action, ""

    def _assess_risk(
        self,
        *,
        customer: Customer,
        days_overdue: int,
        customer_total_outstanding: Decimal,
    ) -> tuple[RiskLevel, float, str]:
        over_limit = (
            customer.credit_limit is not None
            and customer_total_outstanding > customer.credit_limit
        )

        if over_limit and days_overdue > 60:
            return (
                RiskLevel.CRITICAL,
                0.9,
                f"Customer is over their credit limit ({customer.credit_limit}) "
                f"AND this invoice is severely overdue ({days_overdue} days).",
            )
        if over_limit:
            return (
                RiskLevel.HIGH,
                0.85,
                f"Customer's total outstanding balance ({customer_total_outstanding}) "
                f"exceeds their credit limit ({customer.credit_limit}).",
            )
        if days_overdue > 60:
            return (
                RiskLevel.HIGH,
                0.85,
                f"Invoice is {days_overdue} days overdue — significantly delinquent.",
            )
        if days_overdue > 30:
            return (
                RiskLevel.MEDIUM,
                0.8,
                f"Invoice is {days_overdue} days overdue — beyond normal terms.",
            )
        if days_overdue > 0:
            return (
                RiskLevel.LOW,
                0.9,
                f"Invoice is {days_overdue} days overdue — within normal follow-up range.",
            )
        return (
            RiskLevel.LOW,
            0.95,
            "Invoice is not overdue and the customer is within their credit limit.",
        )


def _parse_llm_json(raw_text: str) -> dict | None:
    """Same strict-ish JSON extraction as the AP agent — see
    app.agents.accounts_payable.agent._parse_llm_json for the identical
    logic. Duplicated rather than imported across agent packages to
    keep each agent module independently readable; if a third agent
    needs the same helper, that's the signal to promote it to a shared
    app.agents.json_utils module."""
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
