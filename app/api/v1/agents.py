"""
app.api.v1.agents
====================
HTTP entrypoint for running agents on demand. Runs the agent inline
(awaited within the request) so the caller gets the `AgentResult`
— including any `AgentDecision`s and whether approval is required —
immediately. For high-volume/batch use (e.g. re-matching every invoice
overnight), use a Celery task directly instead of this endpoint — see
`app.workers.tasks`.

Both endpoints here only ever produce a *recommendation*. Nothing in
this router changes any status to APPROVED, sends money, or applies a
credit memo — those all require a human calling the relevant
approval/action endpoint, per the platform's core AI-approval rule.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.accounts_payable.agent import AccountsPayableAgent
from app.agents.accounts_receivable.agent import AccountsReceivableAgent
from app.agents.bank_reconciliation.agent import BankReconciliationAgent
from app.agents.budget_planning.agent import BudgetPlanningAgent
from app.agents.collections.agent import CollectionsAgent
from app.agents.compliance.agent import ComplianceAgent
from app.agents.finance_director.agent import FinanceDirectorAgent
from app.agents.fraud_detection.agent import FraudDetectionAgent
from app.agents.sap_integration.agent import SAPIntegrationAgent
from app.agents.tax.agent import TaxAgent
from app.agents.treasury.agent import TreasuryAgent
from app.agents.schemas import AgentContext, AgentResult
from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.core.logging import get_correlation_id
from app.core.security import role_has_permission
from app.db.session import get_db
from app.schemas.agent import (
    RunAccountsPayableAgentRequest,
    RunAccountsReceivableAgentRequest,
    RunBankReconciliationAgentRequest,
    RunBudgetPlanningAgentRequest,
    RunCollectionsAgentRequest,
    RunComplianceAgentRequest,
    RunFinanceDirectorAgentRequest,
    RunFraudDetectionAgentRequest,
    RunSAPIntegrationAgentRequest,
    RunTaxAgentRequest,
    RunTreasuryAgentRequest,
)

from app.schemas.agent_catalog import AgentCatalogEntry, AgentInputField


_AGENT_CATALOG = [
    ("accounts_payable", "Accounts Payable", "Invoice review, matching, risk narrative and approval routing.", "/agents/accounts-payable/run", RunAccountsPayableAgentRequest),
    ("accounts_receivable", "Accounts Receivable", "AR invoice assessment and exception detection.", "/agents/accounts-receivable/run", RunAccountsReceivableAgentRequest),
    ("collections", "Collections / Aging", "Portfolio or customer-level collection priority and next-best action.", "/agents/collections/run", RunCollectionsAgentRequest),
    ("tax", "Tax", "Sales-tax reasonableness and withholding-tax recommendation.", "/agents/tax/run", RunTaxAgentRequest),
    ("bank_reconciliation", "Bank Reconciliation", "Deterministic statement matching with controlled AI disambiguation.", "/agents/bank-reconciliation/run", RunBankReconciliationAgentRequest),
    ("fraud_detection", "Fraud Detection", "Payment and vendor fraud signals with deterministic risk scoring.", "/agents/fraud-detection/run", RunFraudDetectionAgentRequest),
    ("treasury", "Treasury", "Forward cash-flow forecast and liquidity risk assessment.", "/agents/treasury/run", RunTreasuryAgentRequest),
    ("budget_planning", "Budget Planning", "Pace-adjusted variance and risk by budget.", "/agents/budget-planning/run", RunBudgetPlanningAgentRequest),
    ("compliance", "Compliance / FBR", "Withholding liability versus recorded remittance for a period.", "/agents/compliance/run", RunComplianceAgentRequest),
    ("finance_director", "Finance Director", "Executive orchestration across Treasury, Compliance and Budget Planning.", "/agents/finance-director/run", RunFinanceDirectorAgentRequest),
    ("sap_integration", "SAP Business One Integration", "Synchronize customer/vendor master data through the SAP integration agent; requires agent:configure.", "/agents/sap-integration/run", RunSAPIntegrationAgentRequest),
]

def _input_kind(field_schema: dict) -> tuple[str, list[str]]:
    if field_schema.get("anyOf"):
        candidates = [item for item in field_schema["anyOf"] if item.get("type") != "null"]
        field_schema = candidates[0] if candidates else field_schema
    if field_schema.get("enum"):
        return "select", [str(value) for value in field_schema["enum"]]
    fmt = field_schema.get("format")
    if fmt == "uuid":
        return "uuid", []
    if fmt == "date":
        return "date", []
    if field_schema.get("type") == "integer" or field_schema.get("type") == "number":
        return "number", []
    return "text", []

def _build_catalog_entry(key: str, name: str, description: str, endpoint: str, request_model: type) -> AgentCatalogEntry:
    schema = request_model.model_json_schema()
    required = set(schema.get("required", []))
    properties = schema.get("properties", {})
    fields = []
    for field_name, model_field in request_model.model_fields.items():
        field_schema = properties.get(field_name, {})
        kind, options = _input_kind(field_schema)
        fields.append(AgentInputField(
            name=field_name,
            label=field_name.replace("_", " ").title(),
            kind=kind,
            required=field_name in required,
            description=model_field.description,
            options=options,
        ))
    return AgentCatalogEntry(key=key, name=name, description=description, endpoint=endpoint, input_fields=fields)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/catalog", response_model=list[AgentCatalogEntry])
async def list_agent_catalog(
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> list[AgentCatalogEntry]:
    """Return the actual invocation schemas used by the agent routes.

    The frontend consumes this endpoint instead of maintaining a second,
    drift-prone list of guessed request fields.
    """
    catalog = _AGENT_CATALOG
    if not role_has_permission(actor.role, Permission.AGENT_CONFIGURE):
        catalog = [item for item in catalog if item[0] != "sap_integration"]
    return [_build_catalog_entry(*item) for item in catalog]


@router.post("/accounts-payable/run", response_model=AgentResult)
async def run_accounts_payable_agent(
    payload: RunAccountsPayableAgentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> AgentResult:
    agent = AccountsPayableAgent(session)
    context = AgentContext(
        correlation_id=get_correlation_id(),
        tenant_id="default",  # single-tenant in this phase; see note below
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        input_payload={"invoice_id": str(payload.invoice_id)},
    )
    result = await agent.run(context, actor_role=actor.role)
    # The agent's own decisions/status are committed regardless of
    # outcome (FAILED results are still valid audit records) — only a
    # genuine exception should roll back, and BaseAgent.run() already
    # contains those, so we always commit here.
    await session.commit()
    return result


@router.post("/accounts-receivable/run", response_model=AgentResult)
async def run_accounts_receivable_agent(
    payload: RunAccountsReceivableAgentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> AgentResult:
    agent = AccountsReceivableAgent(session)
    context = AgentContext(
        correlation_id=get_correlation_id(),
        tenant_id="default",
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        input_payload={"ar_invoice_id": str(payload.ar_invoice_id)},
    )
    result = await agent.run(context, actor_role=actor.role)
    await session.commit()
    return result


@router.post("/collections/run", response_model=AgentResult)
async def run_collections_agent(
    payload: RunCollectionsAgentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> AgentResult:
    agent = CollectionsAgent(session)
    input_payload: dict = {}
    if payload.customer_id is not None:
        input_payload["customer_id"] = str(payload.customer_id)
    if payload.as_of is not None:
        input_payload["as_of"] = payload.as_of.isoformat()
    context = AgentContext(
        correlation_id=get_correlation_id(),
        tenant_id="default",
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        input_payload=input_payload,
    )
    result = await agent.run(context, actor_role=actor.role)
    # A portfolio-wide run can return several decisions (one per
    # elevated-priority customer) in a single AgentResult — all
    # persisted/committed together here, same as every other agent
    # endpoint; there is nothing partial about "some of this run's
    # decisions committed, others didn't."
    await session.commit()
    return result


@router.post("/sap-integration/run", response_model=AgentResult)
async def run_sap_integration_agent(
    payload: RunSAPIntegrationAgentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AGENT_CONFIGURE)),
) -> AgentResult:
    agent = SAPIntegrationAgent(session)
    context = AgentContext(
        correlation_id=get_correlation_id(),
        tenant_id="default",
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        input_payload={
            "entity_type": payload.entity_type,
            "entity_id": str(payload.entity_id),
        },
    )
    result = await agent.run(context, actor_role=actor.role)
    await session.commit()
    return result


@router.post("/tax/run", response_model=AgentResult)
async def run_tax_agent(
    payload: RunTaxAgentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> AgentResult:
    agent = TaxAgent(session)
    context = AgentContext(
        correlation_id=get_correlation_id(),
        tenant_id="default",
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        input_payload={"invoice_id": str(payload.invoice_id)},
    )
    result = await agent.run(context, actor_role=actor.role)
    await session.commit()
    return result


@router.post("/bank-reconciliation/run", response_model=AgentResult)
async def run_bank_reconciliation_agent(
    payload: RunBankReconciliationAgentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> AgentResult:
    agent = BankReconciliationAgent(session)
    context = AgentContext(
        correlation_id=get_correlation_id(),
        tenant_id="default",
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        input_payload={"statement_line_id": str(payload.statement_line_id)},
    )
    result = await agent.run(context, actor_role=actor.role)
    await session.commit()
    return result


@router.post("/fraud-detection/run", response_model=AgentResult)
async def run_fraud_detection_agent(
    payload: RunFraudDetectionAgentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> AgentResult:
    agent = FraudDetectionAgent(session)
    context = AgentContext(
        correlation_id=get_correlation_id(),
        tenant_id="default",
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        input_payload={"payment_id": str(payload.payment_id)},
    )
    result = await agent.run(context, actor_role=actor.role)
    await session.commit()
    return result


@router.post("/treasury/run", response_model=AgentResult)
async def run_treasury_agent(
    payload: RunTreasuryAgentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> AgentResult:
    agent = TreasuryAgent(session)
    input_payload: dict = {}
    if payload.horizon_days is not None:
        input_payload["horizon_days"] = payload.horizon_days
    if payload.as_of is not None:
        input_payload["as_of"] = payload.as_of.isoformat()
    context = AgentContext(
        correlation_id=get_correlation_id(),
        tenant_id="default",
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        input_payload=input_payload,
    )
    result = await agent.run(context, actor_role=actor.role)
    await session.commit()
    return result


@router.post("/budget-planning/run", response_model=AgentResult)
async def run_budget_planning_agent(
    payload: RunBudgetPlanningAgentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> AgentResult:
    agent = BudgetPlanningAgent(session)
    input_payload: dict = {"budget_id": str(payload.budget_id)}
    if payload.as_of is not None:
        input_payload["as_of"] = payload.as_of.isoformat()
    context = AgentContext(
        correlation_id=get_correlation_id(),
        tenant_id="default",
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        input_payload=input_payload,
    )
    result = await agent.run(context, actor_role=actor.role)
    await session.commit()
    return result


@router.post("/compliance/run", response_model=AgentResult)
async def run_compliance_agent(
    payload: RunComplianceAgentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> AgentResult:
    agent = ComplianceAgent(session)
    input_payload: dict = {
        "period_start": payload.period_start.isoformat(),
        "period_end": payload.period_end.isoformat(),
    }
    if payload.as_of is not None:
        input_payload["as_of"] = payload.as_of.isoformat()
    context = AgentContext(
        correlation_id=get_correlation_id(),
        tenant_id="default",
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        input_payload=input_payload,
    )
    result = await agent.run(context, actor_role=actor.role)
    await session.commit()
    return result


@router.post("/finance-director/run", response_model=AgentResult)
async def run_finance_director_agent(
    payload: RunFinanceDirectorAgentRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.AGENT_INVOKE)),
) -> AgentResult:
    agent = FinanceDirectorAgent(session)
    input_payload: dict = {
        "period_start": payload.period_start.isoformat(),
        "period_end": payload.period_end.isoformat(),
    }
    if payload.as_of is not None:
        input_payload["as_of"] = payload.as_of.isoformat()
    if payload.treasury_horizon_days is not None:
        input_payload["treasury_horizon_days"] = payload.treasury_horizon_days
    context = AgentContext(
        correlation_id=get_correlation_id(),
        tenant_id="default",
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        input_payload=input_payload,
    )
    result = await agent.run(context, actor_role=actor.role)
    await session.commit()
    return result
