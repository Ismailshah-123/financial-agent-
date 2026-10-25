"""
tests.integration.conftest
=============================
Fixtures for integration tests: these exercise the actual FastAPI app
(`app.main.create_app`) end-to-end via HTTP, through an in-process ASGI
transport (`httpx.ASGITransport`) — no real network socket, but every
other layer (routing, dependency injection, auth, services,
repositories, the ORM, and Postgres itself) is real.

WHY A SEPARATE TEST ENGINE, NOT `app.db.session.engine`
----------------------------------------------------------------------
The app's production engine pools connections (`pool_size`/
`max_overflow`), and a pooled asyncpg connection is bound to whichever
event loop was running when it was first checked out. pytest-asyncio
hands out a fresh loop per scope (per test, by default), so a pooled
connection checked out under one loop and reused under another
desyncs the asyncpg protocol — this surfaced as opaque
`"unknown protocol state"` / `"Event loop is closed"` errors, not a
clear "wrong event loop" message. `_test_engine` below uses
`NullPool`, which opens a fresh low-level connection per checkout and
closes it on checkin, so no connection object ever outlives the loop
that created it. The FastAPI app's `get_db` dependency is overridden
(see the `client` fixture) to use this engine instead, via
`app.dependency_overrides` — the standard FastAPI pattern for this
exact situation.

REQUIRES A RUNNING POSTGRES, POINTED AT A DEDICATED TEST DATABASE
----------------------------------------------------------------------
These tests create and drop real tables. Point `DB_NAME` at a database
that is NOT your development database before running them:

    DB_NAME=finance_ai_db_test pytest tests/integration

(or export `DB_NAME=finance_ai_db_test` in your shell / a `.env.test`
file loaded before the run). Running against your dev database's name
will drop its tables at the end of the test session — this is a
deliberate loud requirement, not a silent default, because getting it
wrong is destructive.

Tables are created from `Base.metadata` (the live model definitions),
not by running the Alembic migration — these tests validate "do the
current models + services + API work correctly together", which is a
different (complementary) question from "does the migration file
correctly reconstruct that schema", which is what `alembic check`
(mentioned in `0001_initial_schema`'s docstring) validates separately.
Because of this, seed data from migrations `0004_chart_of_accounts.py`
and `0005_tax_codes.py` is NOT present automatically — this fixture
reproduces both directly (see `_SEED_ACCOUNTS` / `_SEED_TAX_CODES`
below) so `FinancialReportingService`'s "every posted account must be
in the chart of accounts" invariant and any test exercising a seeded
tax code (e.g. `PK-GST-STD`) don't fail before they even get to what
they're actually testing.

TEST ISOLATION STRATEGY
--------------------------
Route handlers call `session.commit()` internally (see any
`app/api/v1/*.py` router), so a simple "rollback after each test"
fixture would not undo their writes. Rather than truncate every table
between tests (slower, and masks bugs where one test's data should
never have been visible to another), each test generates globally-
unique identifiers (vendor names, invoice numbers, emails) via a
`unique_suffix` fixture, so tests never collide regardless of execution
order — the standard pragmatic pattern for integration tests against a
real, shared-schema database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.db.models  # noqa: F401 — populates Base.metadata before create_all
from app.core.config import settings
from app.db.base import Base
from app.db.models.chart_of_account import ChartOfAccount
from app.db.models.tax_code import TaxCode
from app.db.session import get_db
from app.main import create_app

# Mirrors the seed data in alembic/versions/0004_chart_of_accounts.py and
# 0006_withholding_tax.py — these tests build their schema from
# Base.metadata (current model definitions), not by running migrations, so
# this platform's own "every posted account must be in the chart of
# accounts" invariant (see app.services.financial_reporting_service) needs
# the same seed data reproduced here, or every report/withholding test
# would fail immediately.
_SEED_ACCOUNTS = [
    ("1000-CASH", "Cash", "asset", False),
    ("1100-AR", "Accounts Receivable", "asset", False),
    ("2000-AP", "Accounts Payable", "liability", False),
    ("4000-REV", "Revenue", "revenue", False),
    ("5000-EXP", "General Expense", "expense", False),
    ("5100-PURRET", "Purchase Returns", "expense", True),
    ("2100-WHT", "Withholding Tax Payable", "liability", False),
    ("3000-RE", "Retained Earnings", "equity", False),
]

# Mirrors alembic/versions/0005_tax_codes.py — same "these are
# illustrative, not verified-current FBR/SRB rates" caveat applies here
# as it does there; see that migration's full docstring.
_SEED_TAX_CODES = [
    ("PK-GST-STD", "Pakistan Federal GST — Standard", "sales_tax", "PK-FEDERAL", "18.000"),
    ("PK-SRB-SERVICES-STD", "Sindh Sales Tax on Services — Standard", "sales_tax", "PK-SINDH", "13.000"),
    ("PK-WHT-153-GOODS-FILER", "Withholding — Goods, Filer", "withholding_tax", "PK-FEDERAL", "4.000"),
    ("PK-WHT-153-GOODS-NONFILER", "Withholding — Goods, Non-Filer", "withholding_tax", "PK-FEDERAL", "8.000"),
    ("PK-WHT-153-SERVICES-FILER", "Withholding — Services, Filer", "withholding_tax", "PK-FEDERAL", "8.000"),
    ("PK-WHT-153-SERVICES-NONFILER", "Withholding — Services, Non-Filer", "withholding_tax", "PK-FEDERAL", "16.000"),
]
_SEED_TAX_CODES_EFFECTIVE_FROM = date(2020, 1, 1)


# See the module docstring for why this is a dedicated NullPool engine
# rather than `app.db.session.engine`.
_test_engine = create_async_engine(settings.database.async_url, poolclass=NullPool)
_TestSessionFactory = async_sessionmaker(
    bind=_test_engine, autoflush=False, autocommit=False, expire_on_commit=False
)


async def _get_test_db() -> AsyncGenerator[AsyncSession, None]:
    """Overrides `app.db.session.get_db` for the app-under-test — same
    shape (yields one session per request, rolls back on error) as the
    real dependency, just bound to `_test_engine`."""
    async with _TestSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _test_schema() -> AsyncGenerator[None, None]:
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with _TestSessionFactory() as session:
        for code, name, account_type, is_contra in _SEED_ACCOUNTS:
            session.add(
                ChartOfAccount(
                    account_code=code,
                    account_name=name,
                    account_type=account_type,
                    is_contra=is_contra,
                )
            )
        for code, name, tax_type, jurisdiction, rate_percent in _SEED_TAX_CODES:
            session.add(
                TaxCode(
                    code=code,
                    name=name,
                    tax_type=tax_type,
                    jurisdiction=jurisdiction,
                    rate_percent=rate_percent,
                    effective_from=_SEED_TAX_CODES_EFFECTIVE_FROM,
                    effective_to=None,
                )
            )
        await session.commit()

    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _test_engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    app.dependency_overrides[get_db] = _get_test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def unique_suffix() -> str:
    """A short, collision-resistant suffix for building unique test data
    (emails, vendor names, invoice numbers) so tests never collide
    against the shared test database regardless of execution order."""
    return uuid.uuid4().hex[:10]
