"""
Integration tests for ComplianceAgent and the FBR remittances API,
against real Postgres.

DATE ISOLATION: uses 2028 throughout — a year nothing else in this
suite touches. Withholding tax liability is seeded by posting directly
via PostingService (crediting 2100-WHT), same technique used
throughout this session, since there's no simple API path to produce
an exact, dated withholding liability without going through the full
AP approval chain.
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


async def _seed_withholding_liability(amount: Decimal, posting_date: date) -> None:
    async with _TestSessionFactory() as session:
        posting_service = PostingService(session)
        await posting_service.post(
            transaction_type=TransactionType.AP_INVOICE,
            reference_id=uuid.uuid4(),
            posting_date=posting_date,
            currency=Currency.PKR,
            lines=[
                PostingLine(account_code=DefaultAccounts.ACCOUNTS_PAYABLE, debit=amount),
                PostingLine(account_code=DefaultAccounts.WITHHOLDING_TAX_PAYABLE, credit=amount),
            ],
            actor_id="00000000-0000-0000-0000-000000000000",
        )
        await session.commit()


async def test_fully_remitted_period_is_low_risk(client: AsyncClient, unique_suffix: str) -> None:
    await _seed_withholding_liability(Decimal("5000.00"), date(2028, 1, 15))

    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)

    remit_response = await client.post(
        "/api/v1/fbr-remittances",
        headers=headers,
        json={
            "period_start": "2028-01-01",
            "period_end": "2028-01-31",
            "amount_remitted": "5000.00",
            "currency": "PKR",
            "remitted_date": "2028-02-05",
            "fbr_reference": f"CPR-{unique_suffix}",
        },
    )
    assert remit_response.status_code == 201, remit_response.text

    agent_response = await client.post(
        "/api/v1/agents/compliance/run",
        headers=headers,
        json={"period_start": "2028-01-01", "period_end": "2028-01-31", "as_of": "2028-02-10"},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    assert decision["risk_level"] == "low"
    assert decision["requires_approval"] is False
    assert decision["financial_impact"] is None


async def test_unremitted_and_overdue_is_critical(
    client: AsyncClient, unique_suffix: str
) -> None:
    await _seed_withholding_liability(Decimal("8000.00"), date(2028, 2, 15))

    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)

    # No remittance recorded at all, checked 60 days after period end —
    # well past both the grace period and the critical-overdue boundary.
    agent_response = await client.post(
        "/api/v1/agents/compliance/run",
        headers=headers,
        json={"period_start": "2028-02-01", "period_end": "2028-02-29", "as_of": "2028-04-30"},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    assert decision["risk_level"] == "critical"
    assert decision["requires_approval"] is True
    assert decision["financial_impact"]["amount"] == "8000.00"


async def test_partial_remittance_within_grace_is_medium(
    client: AsyncClient, unique_suffix: str
) -> None:
    await _seed_withholding_liability(Decimal("4000.00"), date(2028, 3, 15))

    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_manager")
    headers = auth_headers(token)

    remit_response = await client.post(
        "/api/v1/fbr-remittances",
        headers=headers,
        json={
            "period_start": "2028-03-01",
            "period_end": "2028-03-31",
            "amount_remitted": "1500.00",
            "currency": "PKR",
            "remitted_date": "2028-04-02",
            "fbr_reference": f"CPR-{unique_suffix}",
        },
    )
    assert remit_response.status_code == 201, remit_response.text

    agent_response = await client.post(
        "/api/v1/agents/compliance/run",
        headers=headers,
        json={"period_start": "2028-03-01", "period_end": "2028-03-31", "as_of": "2028-04-05"},
    )
    assert agent_response.status_code == 200, agent_response.text
    decision = agent_response.json()["decisions"][0]

    assert decision["risk_level"] == "medium"
    assert decision["financial_impact"]["amount"] == "2500.00"


async def test_ap_clerk_cannot_record_remittance(client: AsyncClient, unique_suffix: str) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)
    response = await client.post(
        "/api/v1/fbr-remittances",
        headers=headers,
        json={
            "period_start": "2028-05-01",
            "period_end": "2028-05-31",
            "amount_remitted": "100.00",
            "currency": "PKR",
            "remitted_date": "2028-06-01",
            "fbr_reference": "x",
        },
    )
    assert response.status_code == 403
