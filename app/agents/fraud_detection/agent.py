"""
app.agents.fraud_detection.agent
====================================
`FraudDetectionAgent`: given one `OutgoingPayment`, screens it and its
`Vendor` for fraud signals and produces a single `AgentDecision` — same
one-entity-in shape as every other agent here.

DIFFERENT FROM TaxAgent/BankReconciliationAgent IN ONE IMPORTANT WAY
------------------------------------------------------------------------------
Those agents use an LLM to make judgment calls the deterministic layer
deliberately leaves open (which category, which candidate). This agent
does NOT — every signal and every severity comes from
`FraudDetectionService.detect_signals`, which is 100% rule-based (see
that service's module docstring for why). The LLM here
(`_synthesize_narrative`) only turns an already-decided list of
findings into readable prose; if that call fails, `_synthesize_narrative`
falls back to concatenating the raw signal descriptions — still
completely accurate, just less polished. Fraud screening's risk
determination should never be gated on an LLM provider being
reachable; this agent is built so it isn't.

RISK LEVEL = HIGHEST SEVERITY AMONG THE SIGNALS FOUND
------------------------------------------------------------------------------
See `FraudDetectionService.overall_severity`. No signals -> LOW risk,
still a fully documented decision (see BaseAgent's "even a clean result
gets recorded" convention) — `requires_approval=False` in that case
only; any signal at all sets it True (and a nonzero `financial_impact`
would force it True regardless, via AgentDecision's own validator, once
any signal exists — see below).

FINANCIAL IMPACT
-----------------
Not a proposed new amount (unlike TaxAgent's withholding recommendation
or BankReconciliationAgent's unrecorded-transaction case) — it's the
PAYMENT AMOUNT ITSELF, framed as "amount at risk if this payment is
fraudulent and proceeds anyway." Only set when at least one signal
fired; a clean screening result has nothing at risk to report.

WHAT THIS AGENT NEVER DOES
------------------------------
Never blocks, cancels, or holds the payment — `PaymentService` has no
knowledge this agent exists. Never calls
`VendorService.apply_risk_assessment` — a human reviews this decision
and applies a risk rating / status change separately (see that
method's docstring), same "AI never transacts without approval" rule
as everywhere else in this platform, arguably more important here than
anywhere else in it.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.prompts.fraud_detection_prompts import build_narrative_prompt
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
from app.db.models.payment import OutgoingPayment
from app.db.models.vendor import Vendor
from app.repositories.payment_repository import PaymentRepository
from app.repositories.vendor_repository import VendorRepository
from app.services.fraud_detection_service import FraudDetectionService, FraudSignal, overall_severity

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
    notes=(
        "This agent only screens and reports; it never calls "
        "VendorService.apply_risk_assessment or touches PaymentService, "
        "so there is nothing to roll back."
    ),
)


class FraudDetectionAgent(BaseAgent):
    agent_type = AgentType.FRAUD_DETECTION

    def __init__(self, session: AsyncSession, *, llm_client: LLMClient | None = None) -> None:
        super().__init__(session)
        self.payment_repository = PaymentRepository(session)
        self.vendor_repository = VendorRepository(session)
        self.fraud_service = FraudDetectionService(session)
        self.llm_client = llm_client or get_llm_client()

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        payment_id_raw = context.input_payload.get("payment_id")
        if not payment_id_raw:
            raise AgentExecutionError("input_payload must include 'payment_id'.")
        payment_id = uuid.UUID(str(payment_id_raw))

        payment = await self.payment_repository.get_by_id(payment_id)
        if payment is None:
            raise AgentExecutionError(f"OutgoingPayment {payment_id} not found.")
        vendor = await self.vendor_repository.get_by_id_or_raise(payment.vendor_id)

        signals = await self.fraud_service.detect_signals(payment=payment, vendor=vendor)
        severity = overall_severity(signals)
        narrative = await self._synthesize_narrative(
            vendor=vendor, payment=payment, signals=signals
        )

        financial_impact = None
        if signals:
            financial_impact = FinancialImpact(
                amount=payment.amount,
                currency=Currency(payment.currency),
                impact_type="fraud_screening_amount_at_risk",
            )

        decision = AgentDecision(
            agent_type=self.agent_type,
            summary=_build_summary(severity, signals),
            reasoning=narrative,
            confidence=ConfidenceScore(
                value=1.0 if not signals else 0.9,
                method=ConfidenceMethod.RULE_BASED,
                explanation=(
                    "Every finding is a deterministic rule check; the LLM only "
                    "narrates them, never decides them (see module docstring)."
                ),
            ),
            supporting_evidence=[
                SupportingEvidence(document_id=str(payment.id), document_type="outgoing_payment"),
                SupportingEvidence(document_id=str(vendor.id), document_type="vendor"),
            ],
            relevant_policies=(
                [f"fraud_signal_{s.signal_type}" for s in signals]
                if signals
                else ["fraud_screening_clean_policy"]
            ),
            financial_impact=financial_impact,
            risk_level=_RISK_LEVEL_MAP[severity],
            requires_approval=bool(signals),
            rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
        )
        return [decision]

    async def _synthesize_narrative(
        self, *, vendor: Vendor, payment: OutgoingPayment, signals: list[FraudSignal]
    ) -> str:
        if not signals:
            return (
                f"No fraud signals detected for this {payment.amount} payment to "
                f"{vendor.name}."
            )

        fallback = " ".join(f"[{s.severity.upper()}] {s.description}" for s in signals)
        system_prompt, user_prompt = build_narrative_prompt(
            vendor_name=vendor.name,
            payment_amount=payment.amount,
            signals=[
                {"type": s.signal_type, "severity": s.severity, "description": s.description}
                for s in signals
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
            logger.warning("fraud_narrative_synthesis_failed", error=str(exc))
        return fallback


def _build_summary(severity: str, signals: list[FraudSignal]) -> str:
    if not signals:
        return "No fraud signals detected."
    return f"{len(signals)} fraud signal(s) found — highest severity: {severity}."


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
