"""
app.agents.bank_reconciliation.agent
========================================
`BankReconciliationAgent`: given ONE `BankStatementLine`, produces a
single `AgentDecision` recommending how to resolve it — same
one-entity-in, list-of-decisions-out shape as `TaxAgent` and the AP/AR
agents (see those for the established convention this follows; a
caller reconciling a whole statement invokes this once per unmatched
line, the same way a human would work through one, not something this
agent orchestrates internally).

Delegates all deterministic matching to
`BankReconciliationService.find_candidates` (see that service's module
docstring for the two-tier matching strategy) and only reaches for the
LLM for the two situations the deterministic layer deliberately leaves
open:

- **Multiple same-amount candidates, no bank reference to disambiguate
  them** — `_handle_multiple_candidates` asks the LLM to judge which
  candidate the description text most plausibly refers to
  (`app.agents.prompts.bank_reconciliation_prompts.
  build_disambiguate_match_prompt`), confidence-gated the same way
  `TaxAgent` gates goods/services classification: below
  `_CONFIDENCE_FLOOR`, this degrades to "needs manual review" rather
  than guessing.
- **Zero candidates at all** — `_handle_no_candidates` asks the LLM to
  suggest what KIND of transaction this might be (bank fee, interest,
  bank error, unknown), so a human reviewing it has a starting point
  instead of a blank description.

RISK LEVELS
-----------
- `reference_and_amount` (reference matches AND amount agrees) -> LOW.
  The strongest possible signal.
- `reference_amount_mismatch` (reference matches, amount doesn't) ->
  HIGH. A reference match this strong disagreeing on amount is exactly
  the kind of thing that's either a data error or worth real scrutiny
  — not treated as "probably fine, minor discrepancy."
- Single amount+date-window candidate, no reference -> MEDIUM. Plausible,
  unconfirmed by a reference.
- LLM-disambiguated among multiple candidates, confident -> MEDIUM (same
  reasoning as above, plus the extra uncertainty of picking among
  several).
- No candidates, or disambiguation inconclusive -> MEDIUM by default,
  HIGH if the LLM's classification is "bank_error" or itself low-
  confidence/"unknown" — an unrecognized transaction is routine often
  enough (bank fees) that MEDIUM is the right default, but not when
  even a rough guess at what it is comes up empty.

WHAT THIS AGENT NEVER DOES
------------------------------
Never calls `BankReconciliationService.confirm_match` and never posts
anything via `PostingService` — pure recommendation, same rule as every
other agent here. A human confirms a match (or, for an unrecognized
transaction, decides whether and how to record it) as a separate,
explicit action.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.prompts.bank_reconciliation_prompts import (
    build_classify_unmatched_prompt,
    build_disambiguate_match_prompt,
)
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
from app.db.models.bank_statement_line import BankStatementLine
from app.repositories.bank_statement_line_repository import (
    DATE_WINDOW_DAYS,
    BankStatementLineRepository,
)
from app.services.bank_reconciliation_service import BankReconciliationService, MatchCandidate

logger = get_logger(__name__)

# Below this LLM-reported confidence, the agent refuses to guess (which
# candidate; what category) rather than risk a wrong recommendation —
# same convention as TaxAgent._CATEGORY_CONFIDENCE_FLOOR.
_CONFIDENCE_FLOOR = 0.6

_NO_STATE_MUTATED_ROLLBACK = RollbackStrategy(
    is_reversible=True,
    compensating_action="none_required_no_state_mutated",
    notes=(
        "This agent only recommends; it never calls "
        "BankReconciliationService.confirm_match or PostingService, so "
        "there is nothing to roll back."
    ),
)


class BankReconciliationAgent(BaseAgent):
    agent_type = AgentType.BANK_RECONCILIATION

    def __init__(self, session: AsyncSession, *, llm_client: LLMClient | None = None) -> None:
        super().__init__(session)
        self.repository = BankStatementLineRepository(session)
        self.reconciliation_service = BankReconciliationService(session)
        self.llm_client = llm_client or get_llm_client()

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        statement_line_id_raw = context.input_payload.get("statement_line_id")
        if not statement_line_id_raw:
            raise AgentExecutionError("input_payload must include 'statement_line_id'.")
        statement_line_id = uuid.UUID(str(statement_line_id_raw))

        statement_line = await self.repository.get_by_id(statement_line_id)
        if statement_line is None:
            raise AgentExecutionError(f"BankStatementLine {statement_line_id} not found.")

        if statement_line.is_matched:
            return [self._already_matched_decision(statement_line)]

        candidates = await self.reconciliation_service.find_candidates(statement_line)

        if not candidates:
            return [await self._handle_no_candidates(statement_line)]
        if len(candidates) == 1:
            return [self._handle_single_candidate(statement_line, candidates[0])]
        return [await self._handle_multiple_candidates(statement_line, candidates)]

    # ------------------------------------------------------------------
    def _already_matched_decision(self, statement_line: BankStatementLine) -> AgentDecision:
        return AgentDecision(
            agent_type=self.agent_type,
            summary="Already reconciled — nothing to do.",
            reasoning=(
                f"This line is already matched to a {statement_line.matched_payment_type} "
                f"payment ({statement_line.matched_payment_id})."
            ),
            confidence=ConfidenceScore(
                value=1.0, method=ConfidenceMethod.RULE_BASED, explanation="Direct DB state."
            ),
            supporting_evidence=[
                SupportingEvidence(document_id=str(statement_line.id), document_type="bank_statement_line")
            ],
            relevant_policies=[],
            financial_impact=None,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
            rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
        )

    def _handle_single_candidate(
        self, statement_line: BankStatementLine, candidate: MatchCandidate
    ) -> AgentDecision:
        taken_note = (
            " NOTE: this payment is already matched to a different statement line — "
            "investigate before confirming this one too."
            if candidate.already_matched_elsewhere
            else ""
        )

        if candidate.match_reason == "reference_amount_mismatch":
            discrepancy = abs(statement_line.amount) - candidate.payment_amount
            return AgentDecision(
                agent_type=self.agent_type,
                summary=(
                    f"Bank reference matches a {candidate.payment_type} payment, but the "
                    f"amount doesn't — flagged for review."
                ),
                reasoning=(
                    f"bank_reference '{statement_line.bank_reference}' matches "
                    f"{candidate.payment_type} payment {candidate.payment_id} exactly, but "
                    f"the statement shows {abs(statement_line.amount)} while the recorded "
                    f"payment is {candidate.payment_amount} — a {discrepancy} discrepancy. "
                    f"A reference match this specific disagreeing on amount usually means a "
                    f"data-entry error or a bank-side adjustment (fee deducted from the "
                    f"transfer, partial clearance) rather than the wrong payment entirely."
                    f"{taken_note}"
                ),
                confidence=ConfidenceScore(
                    value=0.5,
                    method=ConfidenceMethod.RULE_BASED,
                    explanation="Certain something is wrong; not certain what the resolution is.",
                ),
                supporting_evidence=[
                    SupportingEvidence(document_id=str(statement_line.id), document_type="bank_statement_line"),
                    SupportingEvidence(document_id=str(candidate.payment_id), document_type=candidate.payment_type + "_payment"),
                ],
                relevant_policies=["bank_reconciliation_reference_match_policy"],
                financial_impact=FinancialImpact(
                    amount=abs(discrepancy),
                    currency=Currency(statement_line.currency),
                    impact_type="bank_reconciliation_amount_discrepancy",
                ),
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
            )

        confidence_value = 0.9 if candidate.match_reason == "reference_and_amount" else 0.7
        risk_level = RiskLevel.LOW if candidate.match_reason == "reference_and_amount" else RiskLevel.MEDIUM
        if candidate.already_matched_elsewhere:
            risk_level = RiskLevel.HIGH

        return AgentDecision(
            agent_type=self.agent_type,
            summary=f"Recommend matching to {candidate.payment_type} payment {candidate.payment_id}.",
            reasoning=(
                f"{'bank_reference and amount both agree' if candidate.match_reason == 'reference_and_amount' else 'Amount and date agree, but no bank_reference on either side to confirm it'} "
                f"with the {candidate.payment_type} payment dated {candidate.payment_date} "
                f"for {candidate.payment_amount}.{taken_note}"
            ),
            confidence=ConfidenceScore(
                value=confidence_value,
                method=ConfidenceMethod.RULE_BASED,
                explanation="Deterministic match — see reasoning for which signals agreed.",
            ),
            supporting_evidence=[
                SupportingEvidence(document_id=str(statement_line.id), document_type="bank_statement_line"),
                SupportingEvidence(document_id=str(candidate.payment_id), document_type=candidate.payment_type + "_payment"),
            ],
            relevant_policies=["bank_reconciliation_match_policy"],
            financial_impact=None,
            risk_level=risk_level,
            requires_approval=True,
            rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
        )

    async def _handle_multiple_candidates(
        self, statement_line: BankStatementLine, candidates: list[MatchCandidate]
    ) -> AgentDecision:
        selected_index, confidence, reasoning_text = await self._disambiguate(
            statement_line, candidates
        )

        if selected_index is None or confidence < _CONFIDENCE_FLOOR:
            return AgentDecision(
                agent_type=self.agent_type,
                summary=f"{len(candidates)} equally plausible candidates — needs manual review.",
                reasoning=(
                    f"Found {len(candidates)} {candidates[0].payment_type} payments matching "
                    f"on amount within the date window, none distinguishable by bank_reference. "
                    f"LLM disambiguation was inconclusive: {reasoning_text}"
                ),
                confidence=ConfidenceScore(
                    value=confidence,
                    method=ConfidenceMethod.ENSEMBLE,
                    explanation="Description text did not clearly favor one candidate.",
                ),
                supporting_evidence=[
                    SupportingEvidence(document_id=str(statement_line.id), document_type="bank_statement_line")
                ]
                + [
                    SupportingEvidence(document_id=str(c.payment_id), document_type=c.payment_type + "_payment")
                    for c in candidates
                ],
                relevant_policies=["bank_reconciliation_match_policy"],
                financial_impact=None,
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
                rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
            )

        chosen = candidates[selected_index]
        return AgentDecision(
            agent_type=self.agent_type,
            summary=f"LLM-assisted match: {chosen.payment_type} payment {chosen.payment_id}.",
            reasoning=(
                f"{len(candidates)} same-amount candidates in the date window; selected "
                f"{chosen.payment_type} payment {chosen.payment_id} based on description "
                f"text. {reasoning_text}"
            ),
            confidence=ConfidenceScore(
                value=min(confidence, 0.85),  # capped: never as certain as a reference match
                method=ConfidenceMethod.ENSEMBLE,
                explanation="LLM disambiguation among multiple deterministic candidates.",
            ),
            supporting_evidence=[
                SupportingEvidence(document_id=str(statement_line.id), document_type="bank_statement_line"),
                SupportingEvidence(document_id=str(chosen.payment_id), document_type=chosen.payment_type + "_payment"),
            ],
            relevant_policies=["bank_reconciliation_match_policy"],
            financial_impact=None,
            risk_level=RiskLevel.MEDIUM,
            requires_approval=True,
            rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
        )

    async def _handle_no_candidates(self, statement_line: BankStatementLine) -> AgentDecision:
        category, confidence, reasoning_text = await self._classify_unmatched(statement_line)
        risk_level = (
            RiskLevel.HIGH if category in ("bank_error", "unknown") or confidence < _CONFIDENCE_FLOOR
            else RiskLevel.MEDIUM
        )

        return AgentDecision(
            agent_type=self.agent_type,
            summary=f"No internal record found — likely {category}, recommend a journal entry.",
            reasoning=(
                f"No {'outgoing' if statement_line.amount < 0 else 'incoming'} payment "
                f"matches this line by reference or by amount within "
                f"{DATE_WINDOW_DAYS} days. LLM classification: {reasoning_text}"
            ),
            confidence=ConfidenceScore(
                value=confidence,
                method=ConfidenceMethod.ENSEMBLE,
                explanation=f"LLM-suggested category: {category}.",
            ),
            supporting_evidence=[
                SupportingEvidence(document_id=str(statement_line.id), document_type="bank_statement_line")
            ],
            relevant_policies=["bank_reconciliation_unmatched_item_policy"],
            financial_impact=FinancialImpact(
                amount=abs(statement_line.amount),
                currency=Currency(statement_line.currency),
                impact_type="bank_reconciliation_unrecorded_transaction",
            ),
            risk_level=risk_level,
            requires_approval=True,
            rollback_strategy=_NO_STATE_MUTATED_ROLLBACK,
        )

    # ------------------------------------------------------------------
    async def _disambiguate(
        self, statement_line: BankStatementLine, candidates: list[MatchCandidate]
    ) -> tuple[int | None, float, str]:
        system_prompt, user_prompt = build_disambiguate_match_prompt(
            statement_description=statement_line.description,
            statement_amount=statement_line.amount,
            statement_date=statement_line.transaction_date,
            candidates=[
                {
                    "index": i,
                    "date": c.payment_date.isoformat(),
                    "reference": c.payment_reference,
                }
                for i, c in enumerate(candidates)
            ],
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None:
                index = parsed.get("selected_candidate_index")
                return (
                    int(index) if index is not None else None,
                    float(parsed.get("confidence", 0.0)),
                    str(parsed.get("reasoning", "")),
                )
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("bank_recon_disambiguation_failed", error=str(exc))
        return None, 0.0, "classification unavailable"

    async def _classify_unmatched(
        self, statement_line: BankStatementLine
    ) -> tuple[str, float, str]:
        system_prompt, user_prompt = build_classify_unmatched_prompt(
            statement_description=statement_line.description,
            statement_amount=statement_line.amount,
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None:
                return (
                    str(parsed.get("category", "unknown")),
                    float(parsed.get("confidence", 0.0)),
                    str(parsed.get("reasoning", "")),
                )
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("bank_recon_classification_failed", error=str(exc))
        return "unknown", 0.0, "classification unavailable"


def _parse_llm_json(raw_text: str) -> dict | None:
    """Identical logic to app.agents.accounts_payable.agent._parse_llm_json
    (local copy per this codebase's existing per-agent convention)."""
    import json

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
