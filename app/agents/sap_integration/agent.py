"""
app.agents.sap_integration.agent
===================================
`SAPIntegrationAgent`: syncs a Vendor or Customer master-data record to SAP
Business One via `SAPSyncService` and turns the outcome into an `AgentDecision`.
Financial-document and payment writes are deliberately gated until an
approval-bound execution/reconciliation workflow is available. Same
`BaseAgent` contract as every other agent — read
`app.agents.accounts_payable.agent` first if this is unfamiliar.

WORKFLOW (`_execute`)
------------------------
1. Confirm SAP integration is actually enabled/configured
   (`settings.sap.enabled`) — fail clearly and immediately if not,
   rather than attempting a login that was never going to succeed.
2. Open a `SAPServiceLayerClient` session for the duration of this one
   run (login on entry, logout on exit via `async with`) — an agent run
   does not hold a long-lived SAP session across multiple invocations.
3. Call `SAPSyncService.sync_vendor` or `sync_customer`.
4. Translate the `SyncOutcome` into a decision:
     - `created` / `no_change` -> LOW risk, no LLM call; the caller must hold
       the elevated `agent:configure` permission for master-data sync.
     - `conflict` -> LLM explains the field-level disagreement between
       local data and SAP; HIGH risk, requires approval. The agent
       does NOT pick a winning side — see `SAPSyncService`'s docstring
       for why an automatic overwrite here would be dangerous.
     - `failed` -> LLM translates the raw SAP error; HIGH risk (it
       blocks this record's future SAP-dependent operations), requires
       approval.

WHAT THIS AGENT NEVER DOES
------------------------------
It never overwrites a conflicting field on either side, and it never
retries a failed sync automatically beyond what `SAPServiceLayerClient`
already does for transient network errors. Resolving a conflict or a
persistent failure is a human decision, surfaced here as a
recommendation with full context — not resolved by force.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.llm_client import LLMClient, get_llm_client
from app.agents.prompts.sap_integration_prompts import (
    build_conflict_narrative_prompt,
    build_sync_failure_narrative_prompt,
)
from app.agents.schemas import (
    AgentContext,
    AgentDecision,
    ConfidenceMethod,
    ConfidenceScore,
    RollbackStrategy,
    SupportingEvidence,
)
from app.core.config import settings
from app.core.constants import AgentType, RiskLevel
from app.core.exceptions import AgentExecutionError
from app.core.logging import get_logger
from app.integrations.sap.client import SAPServiceLayerClient
from app.services.sap_sync_service import SAPSyncService, SyncOutcome

logger = get_logger(__name__)


class SAPIntegrationAgent(BaseAgent):
    agent_type = AgentType.SAP_INTEGRATION

    def __init__(self, session: AsyncSession, *, llm_client: LLMClient | None = None) -> None:
        super().__init__(session)
        self.llm_client = llm_client or get_llm_client()

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        if not settings.sap.enabled:
            raise AgentExecutionError(
                "SAP integration is not enabled (SAP_ENABLED=false). Configure "
                "SAP_SERVICE_LAYER_URL, SAP_COMPANY_DB, SAP_USERNAME, and "
                "SAP_PASSWORD, then set SAP_ENABLED=true, before invoking this agent."
            )

        entity_type = context.input_payload.get("entity_type")
        entity_id_raw = context.input_payload.get("entity_id")
        valid_entity_types = ("vendor", "customer")
        if entity_type not in valid_entity_types or not entity_id_raw:
            raise AgentExecutionError(
                f"input_payload must include 'entity_type' (one of "
                f"{valid_entity_types}) and 'entity_id'. Interactive SAP sync only permits customer/vendor master data."
            )
        entity_id = uuid.UUID(str(entity_id_raw))

        async with SAPServiceLayerClient() as sap_client:
            sync_service = SAPSyncService(self.session, sap_client)
            if entity_type == "vendor":
                outcome = await sync_service.sync_vendor(entity_id, actor_id=context.actor_id)
            else:  # the validated interactive contract allows customer or vendor only
                outcome = await sync_service.sync_customer(entity_id, actor_id=context.actor_id)

        decision = await self._build_decision(outcome)
        return [decision]

    async def _build_decision(self, outcome: SyncOutcome) -> AgentDecision:
        supporting_evidence = [
            SupportingEvidence(document_id=str(outcome.entity_id), document_type=outcome.entity_type)
        ]
        sap_reference = outcome.sap_card_code or (
            f"DocEntry {outcome.sap_doc_entry}" if outcome.sap_doc_entry is not None else None
        )
        if outcome.sap_card_code:
            supporting_evidence.append(
                SupportingEvidence(
                    document_id=outcome.sap_card_code, document_type="sap_business_partner"
                )
            )
        elif outcome.sap_doc_entry is not None:
            supporting_evidence.append(
                SupportingEvidence(
                    document_id=str(outcome.sap_doc_entry), document_type="sap_document"
                )
            )

        if outcome.action == "created":
            return AgentDecision(
                agent_type=self.agent_type,
                summary=f"Created new SAP record for this {outcome.entity_type} ({sap_reference}).",
                reasoning=(
                    f"No prior SAP link existed for this {outcome.entity_type}; a new "
                    f"record was created in SAP ({sap_reference})."
                ),
                confidence=ConfidenceScore(
                    value=0.95,
                    method=ConfidenceMethod.RULE_BASED,
                    explanation="SAP accepted the create request.",
                ),
                supporting_evidence=supporting_evidence,
                relevant_policies=["sap_sync_policy"],
                financial_impact=None,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                rollback_strategy=RollbackStrategy(
                    is_reversible=True,
                    compensating_action="clear_local_sap_reference_and_optionally_delete_in_sap",
                ),
            )

        if outcome.action == "no_change":
            return AgentDecision(
                agent_type=self.agent_type,
                summary=f"Already synced ({sap_reference}) — nothing to do.",
                reasoning=(
                    f"This {outcome.entity_type} already has a SAP reference "
                    f"({sap_reference})."
                ),
                confidence=ConfidenceScore(
                    value=1.0, method=ConfidenceMethod.RULE_BASED, explanation="already synced"
                ),
                supporting_evidence=supporting_evidence,
                relevant_policies=["sap_sync_policy"],
                financial_impact=None,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                rollback_strategy=RollbackStrategy(
                    is_reversible=True, compensating_action="no_action_taken"
                ),
            )

        if outcome.action == "conflict":
            narrative, suggested_investigation = await self._get_conflict_narrative(outcome)
            reasoning = narrative
            if suggested_investigation:
                reasoning += f" Suggested investigation: {suggested_investigation}."
            return AgentDecision(
                agent_type=self.agent_type,
                summary=(
                    f"{len(outcome.conflicting_fields)} field(s) differ between the local "
                    f"record and SAP BusinessPartner {outcome.sap_card_code}."
                ),
                reasoning=reasoning,
                confidence=ConfidenceScore(
                    value=0.7,
                    method=ConfidenceMethod.RULE_BASED,
                    explanation="Conflict detection is exact-match arithmetic; 0.7 reflects "
                    "uncertainty about which side is authoritative, not about the "
                    "detection itself.",
                ),
                supporting_evidence=supporting_evidence,
                relevant_policies=["sap_sync_conflict_policy"],
                financial_impact=None,
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                rollback_strategy=RollbackStrategy(
                    is_reversible=True, compensating_action="no_action_taken_pending_human_review"
                ),
            )

        if outcome.action == "reconciliation_required":
            return AgentDecision(
                agent_type=self.agent_type,
                summary=f"SAP sync for this {outcome.entity_type} needs reconciliation before retry.",
                reasoning=(
                    "The SAP mutation ended without a reliable response. The operation may "
                    "already have been accepted by SAP, so the platform intentionally did not "
                    "retry it automatically. Reconcile the SAP record and local reference "
                    "before another mutation attempt. "
                    f"Detail: {outcome.error_message or 'unknown transport outcome'}."
                ),
                confidence=ConfidenceScore(
                    value=1.0,
                    method=ConfidenceMethod.RULE_BASED,
                    explanation="The system knows the mutation outcome is ambiguous and blocked replay.",
                ),
                supporting_evidence=supporting_evidence,
                relevant_policies=["sap_sync_policy", "sap_reconciliation_required_policy"],
                financial_impact=None,
                risk_level=RiskLevel.CRITICAL,
                requires_approval=True,
                rollback_strategy=RollbackStrategy(
                    is_reversible=False,
                    compensating_action="manual_sap_reconciliation_required",
                ),
            )

        # outcome.action == "failed"
        narrative, suggested_check = await self._get_failure_narrative(outcome)
        reasoning = narrative
        if suggested_check:
            reasoning += f" Suggested first check: {suggested_check}."
        return AgentDecision(
            agent_type=self.agent_type,
            summary=f"Sync to SAP failed for this {outcome.entity_type}.",
            reasoning=reasoning,
            confidence=ConfidenceScore(
                value=0.5,
                method=ConfidenceMethod.RULE_BASED,
                explanation="A failure is unambiguous; 0.5 reflects that the root cause "
                "requires human investigation, not that the failure itself is uncertain.",
            ),
            supporting_evidence=supporting_evidence,
            relevant_policies=["sap_sync_policy"],
            financial_impact=None,
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            rollback_strategy=RollbackStrategy(
                is_reversible=True, compensating_action="no_action_taken_sync_did_not_apply"
            ),
        )

    async def _get_conflict_narrative(self, outcome: SyncOutcome) -> tuple[str, str]:
        system_prompt, user_prompt = build_conflict_narrative_prompt(
            entity_type=outcome.entity_type,
            entity_id=str(outcome.entity_id),
            conflicting_fields=outcome.conflicting_fields,
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None:
                return (
                    str(parsed.get("narrative", "")),
                    str(parsed.get("suggested_investigation", "")),
                )
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("sap_agent_llm_conflict_narrative_failed", error=str(exc))

        fields_list = ", ".join(outcome.conflicting_fields.keys())
        return (
            f"Fields differ between the local record and SAP: {fields_list}.",
            "manually compare both records before syncing",
        )

    async def _get_failure_narrative(self, outcome: SyncOutcome) -> tuple[str, str]:
        system_prompt, user_prompt = build_sync_failure_narrative_prompt(
            entity_type=outcome.entity_type,
            entity_id=str(outcome.entity_id),
            error_message=outcome.error_message or "unknown error",
        )
        try:
            response = await self.llm_client.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            parsed = _parse_llm_json(response.content)
            if parsed is not None:
                return (
                    str(parsed.get("narrative", "")),
                    str(parsed.get("suggested_first_check", "")),
                )
        except Exception as exc:  # noqa: BLE001 — degrade, don't fail the run
            logger.warning("sap_agent_llm_failure_narrative_failed", error=str(exc))

        return (
            f"SAP rejected the sync request: {outcome.error_message or 'unknown error'}.",
            "review the SAP error message and this platform's field mapping",
        )


def _parse_llm_json(raw_text: str) -> dict | None:
    """Same strict-ish JSON extraction pattern as the AP/AR agents —
    see app.agents.accounts_payable.agent._parse_llm_json."""
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
