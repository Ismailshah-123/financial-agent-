"""
app.api.v1.reports
=====================
Read-only financial reporting endpoints: Trial Balance, Profit & Loss,
and Balance Sheet — computed on demand from posted journal entries via
`FinancialReportingService`. See that service's docstring for the
documented limitation on the Balance Sheet's equity section (a computed
rollup, not a closed/posted balance) before treating these as
audit-ready output.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.session import get_db
from app.schemas.financial_report import (
    BalanceSheetRead,
    ProfitAndLossRead,
    ReportCurrenciesRead,
    TrialBalanceRead,
)
from app.services.financial_reporting_service import FinancialReportingService

router = APIRouter(prefix="/reports", tags=["reports"])

CurrencyQuery = Annotated[
    str | None,
    Query(
        min_length=3,
        max_length=3,
        pattern="^[A-Za-z]{3}$",
        description=(
            "ISO 4217 currency to report in. Optional only when the reporting window "
            "holds a single posted currency; otherwise the request is refused rather "
            "than combining currencies."
        ),
    ),
]


@router.get("/currencies", response_model=ReportCurrenciesRead)
async def get_report_currencies(
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.REPORT_VIEW)),
) -> ReportCurrenciesRead:
    service = FinancialReportingService(session)
    return ReportCurrenciesRead(currencies=await service.list_posted_currencies())


@router.get("/trial-balance", response_model=TrialBalanceRead)
async def get_trial_balance(
    as_of: date,
    currency: CurrencyQuery = None,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.REPORT_VIEW)),
) -> TrialBalanceRead:
    service = FinancialReportingService(session)
    report = await service.trial_balance(as_of=as_of, currency=currency)
    return TrialBalanceRead.model_validate(report)


@router.get("/profit-and-loss", response_model=ProfitAndLossRead)
async def get_profit_and_loss(
    start_date: date,
    end_date: date,
    currency: CurrencyQuery = None,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.REPORT_VIEW)),
) -> ProfitAndLossRead:
    service = FinancialReportingService(session)
    report = await service.profit_and_loss(
        start_date=start_date, end_date=end_date, currency=currency
    )
    return ProfitAndLossRead.model_validate(report)


@router.get("/balance-sheet", response_model=BalanceSheetRead)
async def get_balance_sheet(
    as_of: date,
    currency: CurrencyQuery = None,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.REPORT_VIEW)),
) -> BalanceSheetRead:
    service = FinancialReportingService(session)
    report = await service.balance_sheet(as_of=as_of, currency=currency)
    return BalanceSheetRead.model_validate(report)
