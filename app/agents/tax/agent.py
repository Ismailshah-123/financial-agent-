"""
app.agents.tax.agent
======================
`TaxAgent`: given an AP invoice, produces two things in one
`AgentDecision`:

1. SALES-TAX REASONABLENESS CHECK — deliberately NOT a "was the
   correct code applied" check. `tax_code` is accepted at invoice
   creation (`InvoiceService.ingest_invoice`) only to compute
   `tax_amount` server-side; it is not persisted onto the `Invoice` row
   (see `app/schemas/invoice.py`'s docstring), and `Vendor` has no
   jurisdiction field — so there is no way, after the fact, to know
   which specific code SHOULD have applied and re-derive an expected
   amount from it. What this agent CAN do with data that actually
   exists: check whether `tax_amount` is consistent with ANY currently
   active tax code's rate (`implied_rate = tax_amount / subtotal *
   100`, compared against `TaxCodeRepository.list_active()`). An amount
   matching no active rate is a genuine anomaly — manual entry error, a
   stale rate, or something needing a human's eyes — even though this
   check can't identify *which* code was intended. Persisting
   `tax_code` on `Invoice` would allow a stronger check; that's a
   schema change, not something this agent works around.

2. WITHHOLDING-TAX RECOMMENDATION — the "natural next integration
   step" flagged, but deliberately not automated, in
   `app.services.tax_service`'s module docstring. Withholding depends
   on the vendor's `filer_status` (captured on `Vendor`) and whether
   the invoice is for goods or services (captured nowhere — classified
   here via LLM from line-item descriptions; see
   `app.agents.prompts.tax_prompts`). This agent computes what WOULD be
   withheld via the existing `TaxCalculationService.calculate_withholding_tax`
   — the same deterministic, already-unit-tested math `PaymentService`
   would eventually use — it recommends, it does not apply.

RISK / APPROVAL
----------------
- A sales-tax amount matching no active code -> HIGH risk regardless of
  the withholding step: a wrong tax amount affects the invoice total,
  independent of anything withholding-related.
- Goods/services classification below `_CATEGORY_CONFIDENCE_FLOOR` (the
  LLM said "ambiguous", failed, or wasn't confident) -> MEDIUM risk,
  `requires_approval=True` set explicitly (not just left to the schema
  validator): a human needs to categorize this manually before any
  withholding figure can be trusted, which is itself an action item
  even though no `financial_impact` is attached yet.
- A confident recommendation with a nonzero withheld amount carries a
  `financial_impact` -> `AgentDecision`'s own validator then forces
  `requires_approval=True`, which is correct: even a well-reasoned
  recommendation to withhold real money gets a human's sign-off before
  it changes what a vendor is actually paid.

WHAT THIS AGENT NEVER DOES
------------------------------
Never calls `PaymentService`, never mutates `Invoice.tax_amount` or any
other row — pure recommendation. Applying an accepted withholding
recommendation happens when a human schedules the payment
(`POST /api/v1/payments` already accepts `withholding_tax_code`
directly — see `tests/integration/test_withholding_tax.py`), not as a
side effect of this agent running.

REAL FBR RATES CAVEAT
----------------------
Like everything else touching Pakistan tax in this codebase: the rates
this agent's recommendations are built on are the illustrative seed
data in `alembic/versions/0005_tax_codes.py`, not verified-current FBR
notifications. This agent recommends correctly *given* those rates; it
cannot vouch for the rates themselves.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.prompts.tax_prompts import build_tax_category_prompt
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
from app.db.models.enums import FilerStatus, TaxType
from app.db.models.invoice import Invoice
from app.db.models.tax_code import TaxCode
from app.db.models.vendor import Vendor
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.tax_code_repository import TaxCodeRepository
from app.repositories.vendor_repository import VendorRepository
from app.services.tax_service import TaxCalculationResult, TaxCalculationService

logger = get_logger(__name__)

# Below this LLM-reported confidence (or an outright "ambiguous"
# category), the agent refuses to guess goods-vs-services rather than
# risk recommending the wrong withholding rate — see module docstring.
_CATEGORY_CONFIDENCE_FLOOR = 0.6

# implied_rate is compared to each active code's rate_percent within
# this tolerance (percentage points) to absorb ROUND_HALF_UP rounding
# on small subtotals, not to loosely "fuzzy match" real discrepancies.
_RATE_MATCH_TOLERANCE = Decimal("0.05")

# (filer_status, category) -> the seeded Section 153 code. Mirrors
# alembic/versions/0005_tax_codes.py exactly; if that seed data changes,
# this mapping must change with it.
_WITHHOLDING_CODE_MAP: dict[tuple[FilerStatus, str], str] = {
    (FilerStatus.FILER, "goods"): "PK-WHT-153-GOODS-FILER",
    (FilerStatus.NON_FILER, "goods"): "PK-WHT-153-GOODS-NONFILER",
    (FilerStatus.FILER, "services"): "PK-WHT-153-SERVICES-FILER",
    (FilerStatus.NON_FILER, "services"): "PK-WHT-153-SERVICES-NONFILER",
}


class TaxAgent(BaseAgent):
    agent_type = AgentType.TAX

    def __init__(self, session: AsyncSession, *, llm_client: LLMClient | None = None) -> None:
        super().__init__(session)
        self.invoice_repository = InvoiceRepository(session)
        self.vendor_repository = VendorRepository(session)
        self.tax_code_repository = TaxCodeRepository(session)
        self.tax_service = TaxCalculationService(session)
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

        # --- Step 1: sales-tax reasonableness ---
        sales_tax_note, sales_tax_anomaly = await self._check_sales_tax_reasonableness(invoice)

        # --- Step 2: withholding-tax recommendation ---
        (
            withholding_note,
            withholding_result,
            needs_manual_categorization,
        ) = await self._recommend_withholding_tax(invoice=invoice, vendor=vendor)

        # --- Step 3: assemble the decision ---
        reasoning = " ".join(part for part in (sales_tax_note, withholding_note) if part)

        if sales_tax_anomaly:
            risk_level = RiskLevel.HIGH
            confidence_value, confidence_explanation = (
                0.4,
                "Recorded tax_amount does not match any currently active tax "
                "code's rate — flagged for manual verification.",
            )
        elif needs_manual_categorization:
            risk_level = RiskLevel.MEDIUM
            confidence_value, confidence_explanation = (
                0.5,
                "Sales tax looks consistent, but goods-vs-services could not be "
                "classified confidently enough to recommend a specific "
                "withholding code.",
            )
        elif withholding_result is not None:
            risk_level = RiskLevel.LOW
            confidence_value, confidence_explanation = (
                0.85,
                "Sales tax consistent with an active rate; withholding "
                "recommendation based on a confident goods/services "
                "classification and the vendor's recorded filer status.",
            )
        else:
            risk_level = RiskLevel.LOW
            confidence_value, confidence_explanation = (
                0.9,
                "Sales tax consistent (or none recorded); no withholding "
                "applicable for this invoice.",
            )

        supporting_evidence = [
            SupportingEvidence(document_id=str(invoice.id), document_type="invoice"),
            SupportingEvidence(document_id=str(vendor.id), document_type="vendor"),
        ]

        relevant_policies = ["sales_tax_rate_reasonableness_check"]
        financial_impact = None
        requires_approval = False
        if withholding_result is not None:
            relevant_policies.append("section_153_withholding_policy")
            financial_impact = FinancialImpact(
                amount=withholding_result.tax_amount,
                currency=Currency(invoice.currency),
                impact_type="tax_withholding_recommended",
            )
        if needs_manual_categorization:
            relevant_policies.append("section_153_withholding_policy")
            requires_approval = True

        decision = AgentDecision(
            agent_type=self.agent_type,
            summary=_build_summary(
                sales_tax_anomaly=sales_tax_anomaly,
                withholding_result=withholding_result,
                needs_manual_categorization=needs_manual_categorization,
            ),
            reasoning=reasoning,
            confidence=ConfidenceScore(
                value=confidence_value,
                method=ConfidenceMethod.ENSEMBLE,
                explanation=confidence_explanation,
            ),
            supporting_evidence=supporting_evidence,
            relevant_policies=relevant_policies,
            financial_impact=financial_impact,
            risk_level=risk_level,
            requires_approval=requires_approval,
            rollback_strategy=RollbackStrategy(
                is_reversible=True,
                compensating_action="none_required_no_state_mutated",
                notes=(
                    "This agent only recommends; it never mutates Invoice, "
                    "Vendor, or any other row, so there is nothing to roll "
                    "back. If an accepted recommendation is later applied at "
                    "payment time, PaymentService's own execution is what "
                    "would need reversing, not this decision."
                ),
            ),
        )
        return [decision]

    # ------------------------------------------------------------------
    # Step 1: sales-tax reasonableness
    # ------------------------------------------------------------------
    async def _check_sales_tax_reasonableness(self, invoice: Invoice) -> tuple[str, bool]:
        if invoice.tax_amount == 0:
            return (
                "No sales tax recorded on this invoice (tax_amount is zero) — "
                "not flagged as an anomaly; many invoices legitimately have "
                "no sales tax (imports, zero-rated or out-of-scope supplies).",
                False,
            )
        if invoice.subtotal == 0:
            # Can't compute an implied rate; flag rather than divide by zero.
            return (
                "tax_amount is nonzero but subtotal is zero — cannot compute "
                "an implied rate; flagged for manual review.",
                True,
            )

        implied_rate = (invoice.tax_amount / invoice.subtotal * Decimal("100")).quantize(
            Decimal("0.001")
        )
        active_codes = await self.tax_code_repository.list_active()
        sales_tax_codes = [c for c in active_codes if TaxType(c.tax_type) == TaxType.SALES_TAX]
        matched_code = _match_rate_to_active_codes(implied_rate, sales_tax_codes)

        if matched_code is not None:
            return (
                f"tax_amount ({invoice.tax_amount}) on subtotal "
                f"({invoice.subtotal}) implies a {implied_rate}% rate, "
                f"consistent with active code '{matched_code.code}' "
                f"({matched_code.name}, {matched_code.rate_percent}%).",
                False,
            )

        configured_rates = ", ".join(
            f"{c.code} ({c.rate_percent}%)" for c in sales_tax_codes
        ) or "none configured"
        return (
            f"tax_amount ({invoice.tax_amount}) on subtotal ({invoice.subtotal}) "
            f"implies a {implied_rate}% rate, which does not match any "
            f"currently active sales tax code ({configured_rates}) within "
            f"tolerance — flagged for manual verification.",
            True,
        )

    # ------------------------------------------------------------------
    # Step 2: withholding-tax recommendation (best-effort LLM
    # classification, degrades to "needs manual categorization" rather
    # than failing the run — same philosophy as the AP agent's LLM
    # narrative steps).
    # ------------------------------------------------------------------
    async def _recommend_withholding_tax(
        self, *, invoice: Invoice, vendor: Vendor
    ) -> tuple[str, TaxCalculationResult | None, bool]:
        if not invoice.lines:
            return (
                "No line items on this invoice to classify for withholding "
                "purposes — skipped.",
                None,
                True,
            )

        category, confidence, category_reasoning = await self._classify_goods_or_services(
            invoice=invoice, vendor=vendor
        )
        if category not in ("goods", "services") or confidence < _CATEGORY_CONFIDENCE_FLOOR:
            return (
                f"Withholding tax may apply, but goods-vs-services "
                f"classification was inconclusive ({category_reasoning}) — "
                f"needs manual categorization before a withholding code can "
                f"be recommended.",
                None,
                True,
            )

        filer_status = vendor.filer_status or FilerStatus.NON_FILER
        filer_note = (
            "unset on vendor record, treated as non-filer (conservative default)"
            if vendor.filer_status is None
            else filer_status.value
        )
        code = _WITHHOLDING_CODE_MAP[(filer_status, category)]

        try:
            result = await self.tax_service.calculate_withholding_tax(
                gross_amount=invoice.total_amount, tax_code=code, as_of=invoice.invoice_date
            )
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("tax_agent_withholding_calc_failed", error=str(exc), code=code)
            return (
                f"Classified as {category} ({category_reasoning}), but "
                f"computing the withholding amount for code '{code}' failed "
                f"({exc}) — needs manual review.",
                None,
                True,
            )

        return (
            f"Classified as {category} ({category_reasoning}); vendor filer "
            f"status is {filer_note}. Recommending code '{result.tax_code}' "
            f"({result.rate_percent}%): withholding {result.tax_amount} from "
            f"the {result.base_amount} payment, leaving "
            f"{result.base_amount - result.tax_amount} to actually transfer.",
            result,
            False,
        )

    async def _classify_goods_or_services(
        self, *, invoice: Invoice, vendor: Vendor
    ) -> tuple[str, float, str]:
        system_prompt, user_prompt = build_tax_category_prompt(invoice=invoice, vendor=vendor)
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None:
                return (
                    str(parsed.get("category", "ambiguous")),
                    float(parsed.get("confidence", 0.0)),
                    str(parsed.get("reasoning", "")),
                )
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("tax_agent_category_classification_failed", error=str(exc))

        return "ambiguous", 0.0, "classification unavailable"


def _match_rate_to_active_codes(
    implied_rate: Decimal, active_sales_tax_codes: list[TaxCode]
) -> TaxCode | None:
    """Pure. Returns the first active SALES_TAX code whose rate is
    within `_RATE_MATCH_TOLERANCE` of `implied_rate`, or None. Split
    out from `_check_sales_tax_reasonableness` (which does the DB fetch
    and the divide-by-subtotal arithmetic) so the actual matching rule
    is unit-testable with plain `TaxCode` instances — no session, no
    event loop — matching this codebase's convention of keeping
    comparison logic separate from the DB call that feeds it (see
    `app.services.tax_service.compute_tax_amount`)."""
    for code in active_sales_tax_codes:
        if abs(implied_rate - code.rate_percent) <= _RATE_MATCH_TOLERANCE:
            return code
    return None


def _build_summary(
    *,
    sales_tax_anomaly: bool,
    withholding_result: TaxCalculationResult | None,
    needs_manual_categorization: bool,
) -> str:
    if sales_tax_anomaly:
        return "Sales tax amount does not match any active tax code — needs review."
    if withholding_result is not None:
        return (
            f"Sales tax OK; recommend withholding {withholding_result.tax_amount} "
            f"({withholding_result.tax_code}) at payment time."
        )
    if needs_manual_categorization:
        return "Sales tax OK; withholding needs manual goods/services categorization."
    return "Sales tax OK; no withholding applicable."


def _parse_llm_json(raw_text: str) -> dict | None:
    """Strict-ish JSON extraction — identical logic to
    app.agents.accounts_payable.agent._parse_llm_json (kept as a local
    copy per this codebase's existing per-agent convention; see that
    module for the canonical version and rationale)."""
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
