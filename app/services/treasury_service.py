"""
app.services.treasury_service
=================================
Deterministic core for cash flow forecasting: current cash position
plus a projection of known future inflows and outflows, walked
chronologically to find the lowest point the balance is projected to
reach. See `app.agents.treasury.agent` for how this becomes a
risk-leveled `AgentDecision`, and — same as
`app.services.fraud_detection_service` — why the LLM there is used only
to narrate this forecast, never to compute or judge it.

WHAT COUNTS AS A FORECASTED INFLOW OR OUTFLOW, AND WHY
------------------------------------------------------------------
- **Inflows**: open (not PAID/VOID) `ARInvoice` rows with `due_date`
  in the horizon, summed by `amount_outstanding` (so a
  PARTIALLY_PAID invoice only contributes what's actually still owed).
  `IncomingPayment` is deliberately NOT a source of forecasted inflows
  — that model's own docstring says it "assumes... created once a bank
  deposit has already been confirmed," i.e. it represents money that
  has ALREADY arrived, not money still expected.
- **Outflows**: `OutgoingPayment` rows with `status=SCHEDULED` and
  `scheduled_date` in the horizon. Deliberately NOT every open AP
  `Invoice` with a due date in range — an invoice that's APPROVED but
  not yet scheduled for payment could be paid on any day up to (or
  past) its due date, and modeling that timing uncertainty well is a
  meaningfully harder problem than this v1 takes on. A SCHEDULED
  payment is a concrete date commitment; an unscheduled approved
  invoice isn't yet. This means the forecast is a floor on outflows,
  not a ceiling — real cash outflow could be higher once currently-
  unscheduled invoices get scheduled. Documented here rather than
  silently assumed away.

WHY EVENTS, NOT DAILY/WEEKLY BUCKETS
--------------------------------------------
`forecast_cash_flow` walks the actual dated events chronologically
rather than bucketing into fixed periods — the thing that matters for
liquidity risk is the LOWEST point the balance reaches and exactly
when, and arbitrary bucket boundaries can hide or misplace that
relative to real transaction dates. With sparse events (the realistic
case for a v1 platform), day-by-day or week-by-week buckets would
mostly be empty rows adding no information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.repositories.ar_invoice_repository import ARInvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.services.financial_reporting_service import FinancialReportingService
from app.services.posting_service import DefaultAccounts

# v1 heuristics — see FraudDetectionService's tuning constants for the
# same "named, not derived from historical data, recalibrate later"
# convention.
HIGH_RISK_BUFFER_RATIO = Decimal("0.10")  # lowest point < 10% of starting balance
MEDIUM_RISK_BUFFER_RATIO = Decimal("0.30")  # lowest point < 30% of starting balance


@dataclass(frozen=True)
class CashFlowEvent:
    event_date: date
    amount: Decimal  # positive = inflow, negative = outflow
    source_type: str  # "ar_invoice_due" | "scheduled_payment"
    source_id: str
    description: str


@dataclass(frozen=True)
class CashFlowForecast:
    as_of: date
    horizon_days: int
    starting_balance: Decimal
    ending_balance: Decimal
    lowest_balance: Decimal
    lowest_balance_date: date | None  # None if the lowest point IS the starting balance (no events)
    events: list[CashFlowEvent] = field(default_factory=list)


class TreasuryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ar_invoice_repository = ARInvoiceRepository(session)
        self.payment_repository = PaymentRepository(session)
        self.reporting_service = FinancialReportingService(session)

    async def get_current_cash_balance(self, *, as_of: date) -> Decimal:
        balances = await self.reporting_service._account_balances(
            start_date=None, end_date=as_of
        )
        for account_balance in balances:
            if account_balance.account_code == DefaultAccounts.CASH:
                return account_balance.balance
        return Decimal("0")  # no cash activity posted yet

    async def forecast_cash_flow(
        self, *, as_of: date, horizon_days: int
    ) -> CashFlowForecast:
        if horizon_days <= 0:
            raise ValidationError(f"horizon_days must be positive, got {horizon_days}.")

        starting_balance = await self.get_current_cash_balance(as_of=as_of)
        horizon_end = as_of + timedelta(days=horizon_days)

        events: list[CashFlowEvent] = []

        open_invoices = await self.ar_invoice_repository.list_due_within_range(
            start_date=as_of, end_date=horizon_end
        )
        for invoice in open_invoices:
            if invoice.amount_outstanding <= 0:
                continue  # fully offset by credits even though not PAID
            events.append(
                CashFlowEvent(
                    event_date=invoice.due_date,
                    amount=invoice.amount_outstanding,
                    source_type="ar_invoice_due",
                    source_id=str(invoice.id),
                    description=f"AR invoice {invoice.invoice_number} due",
                )
            )

        scheduled_payments = await self.payment_repository.list_scheduled_within_range(
            start_date=as_of, end_date=horizon_end
        )
        for payment in scheduled_payments:
            events.append(
                CashFlowEvent(
                    event_date=payment.scheduled_date,
                    amount=-payment.amount,
                    source_type="scheduled_payment",
                    source_id=str(payment.id),
                    description=f"Scheduled payment {payment.payment_number}",
                )
            )

        events.sort(key=lambda e: e.event_date)
        ending_balance, lowest_balance, lowest_balance_date = _walk_events(
            starting_balance=starting_balance, events=events
        )

        return CashFlowForecast(
            as_of=as_of,
            horizon_days=horizon_days,
            starting_balance=starting_balance,
            ending_balance=ending_balance,
            lowest_balance=lowest_balance,
            lowest_balance_date=lowest_balance_date,
            events=events,
        )


def _walk_events(
    *, starting_balance: Decimal, events: list[CashFlowEvent]
) -> tuple[Decimal, Decimal, date | None]:
    """Pure. Walks `events` (assumed pre-sorted by date) cumulatively
    from `starting_balance`, returning (ending_balance, lowest_balance,
    lowest_balance_date). Split out from forecast_cash_flow (which does
    the DB fetching) so this arithmetic — the actual core of what this
    service computes — is unit-testable with plain CashFlowEvent
    instances, no session, matching this codebase's established
    convention (see e.g. app.agents.tax.agent._match_rate_to_active_codes)
    of keeping comparison/arithmetic logic separate from the DB calls
    that feed it."""
    running_balance = starting_balance
    lowest_balance = starting_balance
    lowest_balance_date: date | None = None
    for cash_flow_event in events:
        running_balance += cash_flow_event.amount
        if running_balance < lowest_balance:
            lowest_balance = running_balance
            lowest_balance_date = cash_flow_event.event_date
    return running_balance, lowest_balance, lowest_balance_date


def assess_liquidity_risk(forecast: CashFlowForecast) -> str:
    """Pure. 'low' | 'medium' | 'high' | 'critical', based on how far
    (and whether) the lowest projected point dips relative to the
    starting balance. See module-level tuning constants."""
    if forecast.lowest_balance < 0:
        return "critical"
    if forecast.starting_balance <= 0:
        # Already at/below zero, and didn't go negative (caught above)
        # — by construction, _walk_events's lowest_balance can never
        # exceed starting_balance, so reaching here always means
        # lowest_balance == starting_balance == 0 exactly. Already
        # being at zero cash is a live problem regardless of whether
        # the forecast shows it getting worse.
        return "high"

    ratio = forecast.lowest_balance / forecast.starting_balance
    if ratio < HIGH_RISK_BUFFER_RATIO:
        return "high"
    if ratio < MEDIUM_RISK_BUFFER_RATIO:
        return "medium"
    return "low"
