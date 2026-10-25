"""
app.agents.accounts_payable.agent
====================================
`AccountsPayableAgent`: given an invoice, decides whether it should be
recommended for approval. This is the reference implementation every
other agent in the platform follows — read this file alongside
`app.agents.base_agent` to understand the pattern before building the
next agent (AR, Tax, Treasury, ...).

WORKFLOW (`_execute`)
------------------------
1. Load the invoice, its vendor, and (if present) its purchase order +
   any posted goods receipts.
2. Duplicate check — same vendor + invoice number already on file
   (`InvoiceService.find_duplicate`). A likely true duplicate is an
   automatic CRITICAL-risk signal, independent of how well the line
   items match.
3. Deterministic 3-way/2-way match (`InvoiceMatchingEngine`, a service —
   see its module docstring for why matching arithmetic lives there and
   not here) and persist the outcome onto the invoice row.
4. LLM-assisted narrative: turn the deterministic match result into a
   plain-language explanation for the human approver, and let the model
   flag qualitative concerns the deterministic engine can't (unusual
   vendor name, odd dates). This call is best-effort — if every
   configured LLM provider fails, the agent falls back to a
   template-generated narrative rather than failing the whole run. A
   finance agent must degrade gracefully, not go dark, when an LLM
   provider has an outage.
5. Risk assessment (`_assess_risk`) — deterministic rules, not the LLM,
   decide the final `RiskLevel`. The LLM's `additional_risk_flagged`
   output is one input to that decision, never the sole determinant.
6. Build one `AgentDecision` covering everything above. The
   `AgentDecision` schema's own validators (see app.agents.schemas)
   are the final backstop: this agent could get its own risk
   classification wrong and the schema will still refuse to construct a
   HIGH/CRITICAL-risk or financially-impactful decision with
   `requires_approval=False`.

WHAT THIS AGENT NEVER DOES
------------------------------
It never calls `PaymentService` and never marks an invoice `APPROVED` —
approval is a human action (`InvoiceService.approve`, invoked from the
API layer once a human accepts this agent's `AgentDecision`), per the
platform's "AI never transacts without approval" rule. This agent's job
ends at producing a well-reasoned recommendation.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.prompts.accounts_payable_prompts import (
    build_duplicate_narrative_prompt,
    build_match_narrative_prompt,
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
from app.db.models.enums import MatchType
from app.db.models.invoice import Invoice
from app.db.models.purchase_order import PurchaseOrder
from app.db.models.vendor import Vendor
from app.repositories.goods_receipt_repository import GoodsReceiptRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.purchase_order_repository import PurchaseOrderRepository
from app.repositories.vendor_repository import VendorRepository
from app.services.invoice_service import InvoiceService
from app.services.matching_service import InvoiceMatchingEngine, MatchOutcome

logger = get_logger(__name__)

DEFAULT_APPROVAL_THRESHOLD = Decimal("5000.00")


class AccountsPayableAgent(BaseAgent):
    agent_type = AgentType.ACCOUNTS_PAYABLE

    def __init__(self, session: AsyncSession, *, llm_client: LLMClient | None = None) -> None:
        super().__init__(session)
        self.invoice_repository = InvoiceRepository(session)
        self.po_repository = PurchaseOrderRepository(session)
        self.grpo_repository = GoodsReceiptRepository(session)
        self.vendor_repository = VendorRepository(session)
        self.invoice_service = InvoiceService(session)
        self.matching_engine = InvoiceMatchingEngine()
        self.llm_client = llm_client or get_llm_client()

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        invoice_id_raw = context.input_payload.get("invoice_id")
        if not invoice_id_raw:
            raise AgentExecutionError("input_payload must include 'invoice_id'.")
        invoice_id = uuid.UUID(str(invoice_id_raw))

        invoice = await self.invoice_repository.get_by_id_with_lines(invoice_id)
        if invoice is None:
            raise AgentExecutionError(f"Invoice {invoice_id} not found.")
        vendor = await self.vendor_repository.get_by_id_or_raise(invoice.vendor_id)

        # --- Step 1: duplicate check ---
        duplicate_candidate = await self.invoice_service.find_duplicate(invoice)
        likely_true_duplicate = False
        duplicate_narrative = ""
        if duplicate_candidate is not None:
            duplicate_narrative, likely_true_duplicate = await self._get_duplicate_narrative(
                new_invoice=invoice, existing_invoice=duplicate_candidate, vendor=vendor
            )

        # --- Step 2: load PO + goods receipts ---
        purchase_order: PurchaseOrder | None = None
        goods_receipts = []
        if invoice.purchase_order_id is not None:
            purchase_order = await self.po_repository.get_by_id_with_lines(
                invoice.purchase_order_id
            )
            if purchase_order is not None:
                goods_receipts = await self.grpo_repository.list_by_purchase_order(
                    purchase_order.id
                )

        # --- Step 3: deterministic match ---
        outcome = self.matching_engine.match(
            invoice=invoice, purchase_order=purchase_order, goods_receipts=goods_receipts
        )
        await self.invoice_service.apply_match_outcome(
            invoice, outcome, actor_id=context.actor_id
        )

        # --- Step 4: LLM narrative (best-effort) ---
        narrative, additional_risk_flagged, additional_risk_reason = (
            await self._get_match_narrative(
                invoice=invoice, purchase_order=purchase_order, vendor=vendor, outcome=outcome
            )
        )

        # --- Step 5: risk assessment ---
        risk_level, confidence_value, confidence_explanation = self._assess_risk(
            outcome=outcome,
            vendor=vendor,
            invoice=invoice,
            duplicate_found=likely_true_duplicate,
            additional_risk_flagged=additional_risk_flagged,
        )

        reasoning_parts = [narrative]
        if duplicate_candidate is not None:
            reasoning_parts.append(f"Duplicate check: {duplicate_narrative}")
        if additional_risk_flagged:
            reasoning_parts.append(f"Additional concern flagged: {additional_risk_reason}")
        reasoning = " ".join(part for part in reasoning_parts if part)

        supporting_evidence = [
            SupportingEvidence(document_id=str(invoice.id), document_type="invoice")
        ]
        if purchase_order is not None:
            supporting_evidence.append(
                SupportingEvidence(
                    document_id=str(purchase_order.id), document_type="purchase_order"
                )
            )
        for grpo in goods_receipts:
            supporting_evidence.append(
                SupportingEvidence(document_id=str(grpo.id), document_type="goods_receipt")
            )
        if duplicate_candidate is not None:
            supporting_evidence.append(
                SupportingEvidence(
                    document_id=str(duplicate_candidate.id),
                    document_type="invoice_duplicate_candidate",
                )
            )

        relevant_policies = ["three_way_match_policy", "duplicate_invoice_check"]
        if vendor.approval_limit is not None:
            relevant_policies.append("vendor_approval_limit")

        decision = AgentDecision(
            agent_type=self.agent_type,
            summary=outcome.summary,
            reasoning=reasoning,
            confidence=ConfidenceScore(
                value=confidence_value,
                method=ConfidenceMethod.ENSEMBLE,
                explanation=confidence_explanation,
            ),
            supporting_evidence=supporting_evidence,
            relevant_policies=relevant_policies,
            financial_impact=FinancialImpact(
                amount=invoice.total_amount,
                currency=Currency(invoice.currency),
                impact_type="accounts_payable_increase",
            ),
            risk_level=risk_level,
            requires_approval=risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL),
            rollback_strategy=RollbackStrategy(
                is_reversible=True,
                compensating_action="revert_invoice_status_and_void_pending_journal_entry",
                notes=(
                    "Reversible up until a payment is executed against this invoice; "
                    "once OutgoingPayment reaches EXECUTED, reversal requires manual "
                    "reconciliation, not this agent's rollback()."
                ),
            ),
        )
        return [decision]

    # ------------------------------------------------------------------
    # LLM-assisted narrative helpers — both best-effort with a
    # deterministic fallback, so a provider outage degrades gracefully.
    # ------------------------------------------------------------------
    async def _get_match_narrative(
        self,
        *,
        invoice: Invoice,
        purchase_order: PurchaseOrder | None,
        vendor: Vendor,
        outcome: MatchOutcome,
    ) -> tuple[str, bool, str]:
        system_prompt, user_prompt = build_match_narrative_prompt(
            invoice=invoice, purchase_order=purchase_order, vendor=vendor, outcome=outcome
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None:
                return (
                    str(parsed.get("narrative", outcome.summary)),
                    bool(parsed.get("additional_risk_flagged", False)),
                    str(parsed.get("additional_risk_reason", "")),
                )
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("ap_agent_llm_narrative_failed", error=str(exc))

        return outcome.summary, False, ""

    async def _get_duplicate_narrative(
        self, *, new_invoice: Invoice, existing_invoice: Invoice, vendor: Vendor
    ) -> tuple[str, bool]:
        system_prompt, user_prompt = build_duplicate_narrative_prompt(
            new_invoice=new_invoice, existing_invoice=existing_invoice, vendor=vendor
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None:
                return (
                    str(parsed.get("narrative", "")),
                    bool(parsed.get("likely_true_duplicate", True)),
                )
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("ap_agent_llm_duplicate_narrative_failed", error=str(exc))

        # Fallback: without LLM confirmation, treat a same-vendor +
        # same-invoice-number hit as a true duplicate by default — the
        # conservative choice, since silently trusting an unconfirmed
        # duplicate is the higher-risk failure mode.
        return (
            f"Invoice number '{new_invoice.invoice_number}' already exists for vendor "
            f"'{vendor.name}' (existing invoice id: {existing_invoice.id}).",
            True,
        )

    # ------------------------------------------------------------------
    # Deterministic risk assessment — the LLM informs this, never solely
    # decides it.
    # ------------------------------------------------------------------
    def _assess_risk(
        self,
        *,
        outcome: MatchOutcome,
        vendor: Vendor,
        invoice: Invoice,
        duplicate_found: bool,
        additional_risk_flagged: bool,
    ) -> tuple[RiskLevel, float, str]:
        if duplicate_found:
            return (
                RiskLevel.CRITICAL,
                0.95,
                "Likely duplicate invoice detected — routed to critical review "
                "regardless of match result.",
            )

        if not outcome.is_matched:
            return (
                RiskLevel.HIGH,
                0.3,
                f"Match failed ({len(outcome.discrepancies)} discrepancy(ies)); "
                f"requires human review before approval.",
            )

        if outcome.match_type == MatchType.MANUAL:
            return (
                RiskLevel.HIGH,
                0.5,
                "No purchase order on file; manual review is required regardless "
                "of any other signal.",
            )

        if additional_risk_flagged:
            return (
                RiskLevel.HIGH,
                0.6,
                "Line items matched cleanly, but a qualitative concern was "
                "flagged during review and escalates this to high risk.",
            )

        threshold = (
            vendor.approval_limit
            if vendor.approval_limit is not None
            else DEFAULT_APPROVAL_THRESHOLD
        )
        base_confidence = 0.98 if outcome.match_type == MatchType.THREE_WAY else 0.85

        if invoice.total_amount > threshold:
            return (
                RiskLevel.MEDIUM,
                base_confidence,
                f"{outcome.match_type.value} match succeeded, but the invoice "
                f"amount ({invoice.total_amount}) exceeds the approval threshold "
                f"of {threshold}; escalated to medium risk.",
            )

        return (
            RiskLevel.LOW,
            base_confidence,
            f"{outcome.match_type.value} match succeeded within tolerance and "
            f"under the approval threshold of {threshold}.",
        )


def _parse_llm_json(raw_text: str) -> dict | None:
    """Strict-ish JSON extraction: strips common Markdown code-fence
    wrapping some models add despite instructions, then parses. Returns
    None (never raises) on any failure so callers can fall back cleanly."""
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
