"""
app.schemas.agent
===================
Request shapes for the agent-invocation endpoints
(`app.api.v1.agents`). Response shapes reuse `app.agents.schemas`
directly (`AgentResult`, `AgentDecision`) — those are already Pydantic
models designed to be read by a human approver, so wrapping them in a
second, parallel API-schema layer here would just be duplication with
no behavioral difference. This module only needs to exist for the
*input* side, which the internal agent schemas don't model (they
describe what an agent produces, not what triggers it).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel


class RunAccountsPayableAgentRequest(APIModel):
    invoice_id: uuid.UUID


class RunTaxAgentRequest(APIModel):
    invoice_id: uuid.UUID


class RunBankReconciliationAgentRequest(APIModel):
    statement_line_id: uuid.UUID


class RunFraudDetectionAgentRequest(APIModel):
    payment_id: uuid.UUID


class RunTreasuryAgentRequest(APIModel):
    horizon_days: int | None = Field(default=None, ge=1, le=365)
    as_of: date | None = None


class RunBudgetPlanningAgentRequest(APIModel):
    budget_id: uuid.UUID
    as_of: date | None = None


class RunComplianceAgentRequest(APIModel):
    period_start: date
    period_end: date
    as_of: date | None = None


class RunFinanceDirectorAgentRequest(APIModel):
    period_start: date
    period_end: date
    as_of: date | None = None
    treasury_horizon_days: int | None = Field(default=None, ge=1, le=365)


class RunAccountsReceivableAgentRequest(APIModel):
    ar_invoice_id: uuid.UUID


class RunCollectionsAgentRequest(APIModel):
    """`customer_id` omitted -> portfolio-wide run across every customer
    with an open AR balance. `customer_id` given -> assess exactly that
    customer. See CollectionsAgent's module docstring for the two shapes."""

    customer_id: uuid.UUID | None = None
    as_of: date | None = None


class RunSAPIntegrationAgentRequest(APIModel):
    """Interactive SAP sync is master-data only until financial writes have an approved execution path."""
    entity_type: Literal["vendor", "customer"]
    entity_id: uuid.UUID
