"""
Integration tests for BudgetPlanningAgent and the budgets API, against
real Postgres.

DATE ISOLATION: uses 2027 throughout — a year nothing else in this
suite touches (other tests use "today" i.e. 2026, or specific months
in 2026 for test_period_close.py/test_treasury.py). Actual account
activity is seeded by posting directly via PostingService (same
technique used throughout this session), since there's no API path to
backdate a posting to an arbitrary date.
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


async def _post(*, account_code: str, contra_account_code: str, amount, posting_date: date) -> None:
    """Posts `amount` as a debit to account_code / credit to
    contra_account_code (or the reverse — see call sites), dated
    posting_date. A thin wrapper so each test call site reads as
    "post this much expense/revenue activity on this date" without
    repeating PostingService boilerplate."""
    async with _TestSessionFactory() as session:
        posting_service = PostingService(session)
        await posting_service.post(
            transaction_type=TransactionType.AP_INVOICE,
            reference_id=uuid.uuid4(),
            posting_date=posting_date,
            currency=Currency.USD,
            lines=[
                PostingLine(account_code=account_code, debit=amount),
                PostingLine(account_code=contra_account_code, credit=amount),
            ],
            actor_id="00000000-0000-0000-0000-000000000000",
        )
        await session.commit()


async def test_expense_budget_over_pace_is_high_risk(
    client: AsyncClient, unique_suffix: str
) -> None:

    # 6000 spent by day 10 of a 31-day January -> at the day-16
    # checkpoint (elapsed_fraction=0.5, expected_at_pace=5000),
    # variance_ratio = (6000-5000)/10000 = 0.10, exactly the HIGH
    # threshold.
    await _post(
        account_code=DefaultAccounts.GENERAL_EXPENSE,
        contra_account_code=DefaultAccounts.ACCOUNTS_PAYABLE,
        amount=Decimal("6000.00"),
        posting_date=date(2027, 1, 10),
    )

    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)

    budget_response = await client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": f"Jan 2027 Expense Budget {unique_suffix}",
            "account_code": "5000-EXP",
            "period_start": "2027-01-01",
            "period_end": "2027-01-31",
            "budgeted_amount": "10000.00",
            "currency": "USD",
        },
    )
    assert budget_response.status_code == 201, budget_response.text
    budget = budget_response.json()

    agent_response = await client.post(
        "/api/v1/agents/budget-planning/run",
        headers=headers,
        json={"budget_id": budget["id"], "as_of": "2027-01-16"},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    assert decision["risk_level"] == "high"
    assert decision["requires_approval"] is True
    assert decision["financial_impact"] is not None
    assert decision["financial_impact"]["amount"] == "1000.00"  # 10% of 10000


async def test_revenue_budget_shortfall_is_critical(
    client: AsyncClient, unique_suffix: str
) -> None:

    # Only 2000 earned by day 10 of a 28-day February against a 10000
    # target -> a large shortfall vs. pace.
    await _post(
        account_code=DefaultAccounts.REVENUE,
        contra_account_code=DefaultAccounts.ACCOUNTS_RECEIVABLE,
        amount=Decimal("2000.00"),
        posting_date=date(2027, 2, 10),
    )

    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_manager")
    headers = auth_headers(token)

    budget_response = await client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": f"Feb 2027 Revenue Target {unique_suffix}",
            "account_code": "4000-REV",
            "period_start": "2027-02-01",
            "period_end": "2027-02-28",
            "budgeted_amount": "10000.00",
            "currency": "USD",
        },
    )
    assert budget_response.status_code == 201, budget_response.text
    budget = budget_response.json()

    agent_response = await client.post(
        "/api/v1/agents/budget-planning/run",
        headers=headers,
        json={"budget_id": budget["id"], "as_of": "2027-02-15"},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    assert decision["risk_level"] == "critical"
    assert decision["requires_approval"] is True


async def test_budget_against_asset_account_is_not_meaningful(
    client: AsyncClient, unique_suffix: str
) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)

    budget_response = await client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": f"Nonsensical Cash Budget {unique_suffix}",
            "account_code": "1000-CASH",
            "period_start": "2027-03-01",
            "period_end": "2027-03-31",
            "budgeted_amount": "5000.00",
            "currency": "USD",
        },
    )
    assert budget_response.status_code == 201, budget_response.text
    budget = budget_response.json()

    agent_response = await client.post(
        "/api/v1/agents/budget-planning/run",
        headers=headers,
        json={"budget_id": budget["id"], "as_of": "2027-03-15"},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    assert decision["risk_level"] == "low"
    assert decision["requires_approval"] is False
    assert "isn't meaningful" in decision["reasoning"] or "isn't meaningful" in decision["reasoning"].lower()


async def test_ap_clerk_cannot_create_budget(client: AsyncClient, unique_suffix: str) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)
    response = await client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": "x",
            "account_code": "5000-EXP",
            "period_start": "2027-04-01",
            "period_end": "2027-04-30",
            "budgeted_amount": "1000.00",
            "currency": "USD",
        },
    )
    assert response.status_code == 403


async def test_overlapping_budget_is_rejected(client: AsyncClient, unique_suffix: str) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)
    first = await client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": f"May budget {unique_suffix}",
            "account_code": "5100-PURRET",
            "period_start": "2027-05-01",
            "period_end": "2027-05-31",
            "budgeted_amount": "1000.00",
            "currency": "USD",
        },
    )
    assert first.status_code == 201, first.text

    overlapping = await client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": f"Overlapping May budget {unique_suffix}",
            "account_code": "5100-PURRET",
            "period_start": "2027-05-15",
            "period_end": "2027-06-15",
            "budgeted_amount": "500.00",
            "currency": "USD",
        },
    )
    assert overlapping.status_code == 422, overlapping.text
