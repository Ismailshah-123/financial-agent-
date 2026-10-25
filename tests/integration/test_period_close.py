"""
Integration tests for PeriodCloseService via the real API and a real
Postgres instance.

DATE CHOICE: every real posting path in this codebase (ARInvoiceService.
send_invoice, and — by the same pattern — AP invoice approval/payment
execution) hardcodes `posting_date=date.today()`; there's no way to
backdate a posting through the HTTP API. Every other integration test
in this suite therefore posts with today's date. To close a period
without either (a) colliding with today's date, which every other test
also uses, or (b) depending on test execution order, this file seeds
its own journal entries directly via `PostingService` (bypassing
ARInvoiceService/InvoiceService, which is exactly what those services'
hardcoded `date.today()` prevents doing through the API) dated in
January 2026 — safely in the past, and a range nothing else in this
suite ever touches.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.constants import Currency, TransactionType
from app.core.exceptions import ValidationError
from app.services.posting_service import DefaultAccounts, PostingLine, PostingService
from tests.integration.conftest import _TestSessionFactory
from tests.integration.helpers import auth_headers, register_and_login

pytestmark = pytest.mark.asyncio

_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 31)
_POSTING_DATE = date(2026, 1, 15)


def uuid_new():
    import uuid

    return uuid.uuid4()


async def test_close_period_zeroes_pl_and_posts_retained_earnings(
    client: AsyncClient, unique_suffix: str
) -> None:
    from app.services.posting_service import PostingLine

    revenue = Decimal("5000.00")
    expense = Decimal("2000.00")

    async with _TestSessionFactory() as session:
        posting_service = PostingService(session)
        await posting_service.post(
            transaction_type=TransactionType.AR_INVOICE,
            reference_id=uuid_new(),
            posting_date=_POSTING_DATE,
            currency=Currency.PKR,
            lines=[
                PostingLine(account_code=DefaultAccounts.ACCOUNTS_RECEIVABLE, debit=revenue),
                PostingLine(account_code=DefaultAccounts.REVENUE, credit=revenue),
            ],
            actor_id="00000000-0000-0000-0000-000000000000",
        )
        await posting_service.post(
            transaction_type=TransactionType.AP_INVOICE,
            reference_id=uuid_new(),
            posting_date=_POSTING_DATE,
            currency=Currency.PKR,
            lines=[
                PostingLine(account_code=DefaultAccounts.GENERAL_EXPENSE, debit=expense),
                PostingLine(account_code=DefaultAccounts.ACCOUNTS_PAYABLE, credit=expense),
            ],
            actor_id="00000000-0000-0000-0000-000000000000",
        )
        await session.commit()

    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)

    close_response = await client.post(
        "/api/v1/period-close",
        headers=headers,
        json={"start_date": _PERIOD_START.isoformat(), "end_date": _PERIOD_END.isoformat()},
    )
    assert close_response.status_code == 201, close_response.text
    period_close = close_response.json()
    assert period_close["total_revenue"] == "5000.00"
    assert period_close["total_expense"] == "2000.00"
    assert period_close["net_income"] == "3000.00"
    assert period_close["is_reopened"] is False

    # P&L for the now-closed range nets to zero — the closing entry's
    # whole point (see PeriodCloseService's module docstring).
    pnl_response = await client.get(
        "/api/v1/reports/profit-and-loss",
        headers=headers,
        params={"start_date": _PERIOD_START.isoformat(), "end_date": _PERIOD_END.isoformat()},
    )
    assert pnl_response.status_code == 200, pnl_response.text
    assert pnl_response.json()["net_income"] == "0.00"

    # Balance Sheet as of period-end now shows a REAL 3000-RE balance.
    bs_response = await client.get(
        "/api/v1/reports/balance-sheet",
        headers=headers,
        params={"as_of": _PERIOD_END.isoformat()},
    )
    assert bs_response.status_code == 200, bs_response.text
    balance_sheet = bs_response.json()
    equity_by_code = {line["account_code"]: line for line in balance_sheet["equity_lines"]}
    assert equity_by_code["3000-RE"]["balance"] == "3000.00"
    assert balance_sheet["computed_retained_earnings"] == "0.00"
    assert balance_sheet["total_equity"] == "3000.00"
    assert balance_sheet["is_balanced"] is True


async def test_posting_into_closed_period_is_rejected(
    client: AsyncClient, unique_suffix: str
) -> None:
    from app.core.exceptions import ValidationError
    from app.services.posting_service import PostingLine

    async with _TestSessionFactory() as session:
        posting_service = PostingService(session)
        await posting_service.post(
            transaction_type=TransactionType.AR_INVOICE,
            reference_id=uuid_new(),
            posting_date=date(2026, 2, 10),
            currency=Currency.PKR,
            lines=[
                PostingLine(account_code=DefaultAccounts.ACCOUNTS_RECEIVABLE, debit=Decimal("100")),
                PostingLine(account_code=DefaultAccounts.REVENUE, credit=Decimal("100")),
            ],
            actor_id="00000000-0000-0000-0000-000000000000",
        )
        await session.commit()

    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)
    close_response = await client.post(
        "/api/v1/period-close",
        headers=headers,
        json={"start_date": "2026-02-01", "end_date": "2026-02-28"},
    )
    assert close_response.status_code == 201, close_response.text

    # Now try to post something else back-dated into that closed range.
    async with _TestSessionFactory() as session:
        posting_service = PostingService(session)
        with pytest.raises(ValidationError, match="closed period"):
            await posting_service.post(
                transaction_type=TransactionType.AR_INVOICE,
                reference_id=uuid_new(),
                posting_date=date(2026, 2, 15),
                currency=Currency.PKR,
                lines=[
                    PostingLine(
                        account_code=DefaultAccounts.ACCOUNTS_RECEIVABLE, debit=Decimal("50")
                    ),
                    PostingLine(account_code=DefaultAccounts.REVENUE, credit=Decimal("50")),
                ],
                actor_id="00000000-0000-0000-0000-000000000000",
            )


async def test_reopen_period_lifts_the_lock(client: AsyncClient, unique_suffix: str) -> None:
    from app.services.posting_service import PostingLine

    async with _TestSessionFactory() as session:
        posting_service = PostingService(session)
        await posting_service.post(
            transaction_type=TransactionType.AR_INVOICE,
            reference_id=uuid_new(),
            posting_date=date(2026, 3, 10),
            currency=Currency.PKR,
            lines=[
                PostingLine(account_code=DefaultAccounts.ACCOUNTS_RECEIVABLE, debit=Decimal("200")),
                PostingLine(account_code=DefaultAccounts.REVENUE, credit=Decimal("200")),
            ],
            actor_id="00000000-0000-0000-0000-000000000000",
        )
        await session.commit()

    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)
    close_response = await client.post(
        "/api/v1/period-close",
        headers=headers,
        json={"start_date": "2026-03-01", "end_date": "2026-03-31"},
    )
    assert close_response.status_code == 201, close_response.text
    period_close_id = close_response.json()["id"]

    reopen_response = await client.post(
        f"/api/v1/period-close/{period_close_id}/reopen",
        headers=headers,
        json={"reason": "closed the wrong month by mistake"},
    )
    assert reopen_response.status_code == 200, reopen_response.text
    reopened = reopen_response.json()
    assert reopened["is_reopened"] is True
    assert reopened["reopening_journal_entry_id"] is not None

    # Lock is lifted — this should now succeed.
    async with _TestSessionFactory() as session:
        posting_service = PostingService(session)
        entry = await posting_service.post(
            transaction_type=TransactionType.AR_INVOICE,
            reference_id=uuid_new(),
            posting_date=date(2026, 3, 20),
            currency=Currency.PKR,
            lines=[
                PostingLine(account_code=DefaultAccounts.ACCOUNTS_RECEIVABLE, debit=Decimal("75")),
                PostingLine(account_code=DefaultAccounts.REVENUE, credit=Decimal("75")),
            ],
            actor_id="00000000-0000-0000-0000-000000000000",
        )
        await session.commit()
    assert entry.id is not None


async def test_closing_empty_period_is_rejected(client: AsyncClient, unique_suffix: str) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="finance_director")
    headers = auth_headers(token)
    response = await client.post(
        "/api/v1/period-close",
        headers=headers,
        json={"start_date": "2026-04-01", "end_date": "2026-04-30"},
    )
    assert response.status_code == 422, response.text
    assert "nothing to close" in response.text.lower()


async def test_ap_clerk_cannot_close_a_period(client: AsyncClient, unique_suffix: str) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix, role="ap_clerk")
    headers = auth_headers(token)
    response = await client.post(
        "/api/v1/period-close",
        headers=headers,
        json={"start_date": "2026-05-01", "end_date": "2026-05-31"},
    )
    assert response.status_code == 403
