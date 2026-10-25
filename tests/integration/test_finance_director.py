"""
Integration test for FinanceDirectorAgent — the real proof that calling
three sub-agents through their own .run() (not ._execute() directly)
actually works end to end: each sub-agent independently permission-
checks the SAME actor_role, and their combined decisions come back
correctly flattened alongside the synthesis decision.

DATE ISOLATION: uses 2029 throughout — a year nothing else in this
suite touches. Cash balance and withholding liability are seeded by
posting directly via PostingService, same technique used throughout
this session.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.constants import Currency, TransactionType
from app.services.posting_service import DefaultAccounts, PostingLine, PostingService
from tests.integration.conftest import _TestSessionFactory
from tests.integration.helpers import auth_headers, register_and_login

pytestmark = pytest.mark.asyncio


async def test_period_review_orchestrates_all_three_agents(
    client: AsyncClient, unique_suffix: str
) -> None:
    # Cash balance for Treasury.
    async with _TestSessionFactory() as session:
        posting_service = PostingService(session)
        await posting_service.post(
            transaction_type=TransactionType.AR_INVOICE,
            reference_id=uuid.uuid4(),
            posting_date=date(2029, 1, 1),
            currency=Currency.PKR,
            lines=[
                PostingLine(account_code=DefaultAccounts.CASH, debit=Decimal("10000.00")),
                PostingLine(account_code=DefaultAccounts.REVENUE, credit=Decimal("10000.00")),
            ],
            actor_id="00000000-0000-0000-0000-000000000000",
        )
        # Withholding tax liability for Compliance — deliberately left
        # unremitted, so this sub-check has a real finding.
        await posting_service.post(
            transaction_type=TransactionType.AP_INVOICE,
            reference_id=uuid.uuid4(),
            posting_date=date(2029, 1, 15),
            currency=Currency.PKR,
            lines=[
                PostingLine(account_code=DefaultAccounts.ACCOUNTS_PAYABLE, debit=Decimal("2000.00")),
                PostingLine(
                    account_code=DefaultAccounts.WITHHOLDING_TAX_PAYABLE, credit=Decimal("2000.00")
                ),
            ],
            actor_id="00000000-0000-0000-0000-000000000000",
        )
        await session.commit()

    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)

    # A budget overlapping the review period, for Budget Planning.
    budget_response = await client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": f"Jan 2029 Expense Budget {unique_suffix}",
            "account_code": "5000-EXP",
            "period_start": "2029-01-01",
            "period_end": "2029-01-31",
            "budgeted_amount": "1000.00",
            "currency": "PKR",
        },
    )
    assert budget_response.status_code == 201, budget_response.text

    review_response = await client.post(
        "/api/v1/agents/finance-director/run",
        headers=headers,
        json={
            "period_start": "2029-01-01",
            "period_end": "2029-01-31",
            "as_of": "2029-03-15",  # well past the compliance grace period
        },
    )
    assert review_response.status_code == 200, review_response.text
    result = review_response.json()
    decisions = result["decisions"]

    # 1 synthesis + 1 treasury + 1 compliance + 1 budget = 4.
    assert len(decisions) == 4

    synthesis = decisions[0]
    assert synthesis["agent_type"] == "finance_director"
    assert "checks completed" in synthesis["summary"]

    decisions_by_agent = {d["agent_type"]: d for d in decisions[1:]}
    assert set(decisions_by_agent.keys()) == {"treasury", "compliance", "budget_planning"}

    # Compliance should be the worst finding here (unremitted, overdue
    # withholding tax) — the synthesis's overall risk should reflect it.
    assert decisions_by_agent["compliance"]["risk_level"] in ("high", "critical")
    assert synthesis["risk_level"] in ("high", "critical")
    assert synthesis["requires_approval"] is True
    assert synthesis["financial_impact"] is None  # see agent's module docstring


async def test_period_review_with_no_budgets_still_runs(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_manager")
    headers = auth_headers(token)

    review_response = await client.post(
        "/api/v1/agents/finance-director/run",
        headers=headers,
        json={"period_start": "2029-02-01", "period_end": "2029-02-28", "as_of": "2029-02-15"},
    )
    assert review_response.status_code == 200, review_response.text
    decisions = review_response.json()["decisions"]

    # 1 synthesis + 1 treasury + 1 compliance, no budgets configured for Feb 2029.
    assert len(decisions) == 3
    assert decisions[0]["risk_level"] == "low"


async def test_ap_clerk_cannot_run_finance_director_review(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="viewer")
    headers = auth_headers(token)
    response = await client.post(
        "/api/v1/agents/finance-director/run",
        headers=headers,
        json={"period_start": "2029-03-01", "period_end": "2029-03-31"},
    )
    assert response.status_code == 403
