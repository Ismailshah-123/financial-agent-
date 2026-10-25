"""
Unit tests for AccountsReceivableAgent._assess_risk — the deterministic
collection/credit-limit risk rules, tested in isolation from the DB and
LLM, same pattern as tests/unit/test_accounts_payable_agent.py.
"""

from __future__ import annotations

from decimal import Decimal

from app.agents.accounts_receivable.agent import AccountsReceivableAgent
from app.core.constants import RiskLevel
from app.db.models.customer import Customer


def _customer(credit_limit: Decimal | None = None) -> Customer:
    return Customer(
        name="Globex Corp",
        default_currency="USD",
        payment_terms_days=30,
        credit_limit=credit_limit,
    )


def _agent() -> AccountsReceivableAgent:
    return AccountsReceivableAgent.__new__(AccountsReceivableAgent)  # bypass __init__


def test_not_overdue_and_under_limit_is_low_risk() -> None:
    agent = _agent()
    risk, confidence, _ = agent._assess_risk(
        customer=_customer(credit_limit=Decimal("10000")),
        days_overdue=0,
        customer_total_outstanding=Decimal("500"),
    )
    assert risk == RiskLevel.LOW
    assert confidence == 0.95


def test_slightly_overdue_is_low_risk() -> None:
    agent = _agent()
    risk, _, _ = agent._assess_risk(
        customer=_customer(),
        days_overdue=10,
        customer_total_outstanding=Decimal("500"),
    )
    assert risk == RiskLevel.LOW


def test_moderately_overdue_is_medium_risk() -> None:
    agent = _agent()
    risk, _, _ = agent._assess_risk(
        customer=_customer(),
        days_overdue=45,
        customer_total_outstanding=Decimal("500"),
    )
    assert risk == RiskLevel.MEDIUM


def test_severely_overdue_is_high_risk() -> None:
    agent = _agent()
    risk, _, _ = agent._assess_risk(
        customer=_customer(),
        days_overdue=90,
        customer_total_outstanding=Decimal("500"),
    )
    assert risk == RiskLevel.HIGH


def test_over_credit_limit_is_high_risk_even_if_not_overdue() -> None:
    agent = _agent()
    risk, _, _ = agent._assess_risk(
        customer=_customer(credit_limit=Decimal("1000")),
        days_overdue=0,
        customer_total_outstanding=Decimal("1500"),
    )
    assert risk == RiskLevel.HIGH


def test_over_limit_and_severely_overdue_is_critical() -> None:
    agent = _agent()
    risk, _, _ = agent._assess_risk(
        customer=_customer(credit_limit=Decimal("1000")),
        days_overdue=75,
        customer_total_outstanding=Decimal("1500"),
    )
    assert risk == RiskLevel.CRITICAL


def test_no_credit_limit_configured_never_triggers_over_limit_risk() -> None:
    agent = _agent()
    risk, _, _ = agent._assess_risk(
        customer=_customer(credit_limit=None),
        days_overdue=0,
        customer_total_outstanding=Decimal("1_000_000"),
    )
    assert risk == RiskLevel.LOW
