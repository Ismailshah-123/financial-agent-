"""
Unit tests for app.services.posting_service — the balanced-journal-entry
invariant (tested against the pure logic, checked before any repository
call — see PostingService.post's comment on why balance/zero-amount
checks run before the period-lock check) and the period-lock invariant
(PeriodCloseRepository faked, since that check does need a DB query).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.constants import Currency, TransactionType
from app.core.exceptions import ValidationError
from app.services.posting_service import PostingLine, PostingService


class _FakeSession:
    """Minimal stand-in — PostingService only touches the session via
    its repository, which we don't reach in the unbalanced-entry tests
    below since validation raises before any DB call."""


async def test_unbalanced_entry_is_rejected() -> None:
    service = PostingService(session=_FakeSession())  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        await service.post(
            transaction_type=TransactionType.AP_INVOICE,
            reference_id=uuid.uuid4(),
            posting_date=date.today(),
            currency=Currency.USD,
            lines=[
                PostingLine(account_code="5000-EXP", debit=Decimal("100.00")),
                PostingLine(account_code="2000-AP", credit=Decimal("99.00")),
            ],
            actor_id="tester",
        )


async def test_zero_amount_entry_is_rejected() -> None:
    service = PostingService(session=_FakeSession())  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        await service.post(
            transaction_type=TransactionType.AP_INVOICE,
            reference_id=uuid.uuid4(),
            posting_date=date.today(),
            currency=Currency.USD,
            lines=[
                PostingLine(account_code="5000-EXP", debit=Decimal("0")),
                PostingLine(account_code="2000-AP", credit=Decimal("0")),
            ],
            actor_id="tester",
        )


class _FakeJournalEntryRepository:
    """Stand-in for JournalEntryRepository — `add()` just returns
    whatever it's given, as if it had been persisted, so these tests
    can verify the constructed JournalEntry's lines/totals without a
    real database."""

    def __init__(self, session) -> None:
        pass

    async def add(self, entry):
        return entry


class _FakeNoOverlapPeriodCloseRepository:
    """Stand-in for PeriodCloseRepository — always reports no closed
    period overlaps, so these tests can exercise post()'s balanced-entry
    path without a real database. See app.services.posting_service.post's
    period-lock check, added alongside PeriodCloseService."""

    def __init__(self, session) -> None:
        pass

    async def list_overlapping(self, *, start_date, end_date):
        return []


async def test_payment_execution_with_withholding_produces_balanced_three_line_entry(
    monkeypatch,
) -> None:
    """The core correctness property of withholding tax posting: the
    full invoice amount clears AP (debit), but cash only moves the net
    amount (credit) — the difference becomes a liability owed to the
    tax authority instead of vanishing. Verifies this nets to a
    balanced entry, which app.services.posting_service.PostingService.post
    would otherwise reject."""
    import app.services.posting_service as posting_service_module

    monkeypatch.setattr(
        posting_service_module, "JournalEntryRepository", _FakeJournalEntryRepository
    )
    monkeypatch.setattr(
        posting_service_module, "PeriodCloseRepository", _FakeNoOverlapPeriodCloseRepository
    )

    service = PostingService(session=_FakeSession())  # type: ignore[arg-type]
    entry = await service.post_payment_execution(
        payment_id=uuid.uuid4(),
        amount=Decimal("10000.00"),  # full AP liability being cleared
        currency=Currency.PKR,
        posting_date=date.today(),
        actor_id="tester",
        withholding_tax_amount=Decimal("400.00"),
    )

    assert entry.total_debit == Decimal("10000.00")
    assert entry.total_credit == Decimal("10000.00")

    lines_by_code = {line.account_code: line for line in entry.lines}
    assert lines_by_code["2000-AP"].debit == Decimal("10000.00")
    assert lines_by_code["1000-CASH"].credit == Decimal("9600.00")
    assert lines_by_code["2100-WHT"].credit == Decimal("400.00")


async def test_payment_execution_without_withholding_has_only_two_lines(monkeypatch) -> None:
    import app.services.posting_service as posting_service_module

    monkeypatch.setattr(
        posting_service_module, "JournalEntryRepository", _FakeJournalEntryRepository
    )
    monkeypatch.setattr(
        posting_service_module, "PeriodCloseRepository", _FakeNoOverlapPeriodCloseRepository
    )

    service = PostingService(session=_FakeSession())  # type: ignore[arg-type]
    entry = await service.post_payment_execution(
        payment_id=uuid.uuid4(),
        amount=Decimal("5000.00"),
        currency=Currency.USD,
        posting_date=date.today(),
        actor_id="tester",
    )

    assert len(entry.lines) == 2
    assert entry.total_debit == Decimal("5000.00")
    assert entry.total_credit == Decimal("5000.00")


async def test_period_locked_date_is_rejected(monkeypatch) -> None:
    """The other half of the period-lock invariant: an entry that IS
    balanced still gets rejected if posting_date falls inside a closed
    period. See PostingService.post's period-lock check."""
    import uuid as uuid_module

    import app.services.posting_service as posting_service_module
    from app.core.exceptions import ValidationError as VErr
    from app.db.models.period_close import PeriodClose

    closed_period = PeriodClose(
        id=uuid_module.uuid4(),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        closing_journal_entry_id=uuid_module.uuid4(),
        total_revenue=Decimal("0"),
        total_expense=Decimal("0"),
        net_income=Decimal("0"),
    )

    class _FakeLockedPeriodCloseRepository:
        def __init__(self, session) -> None:
            pass

        async def list_overlapping(self, *, start_date, end_date):
            return [closed_period]

    monkeypatch.setattr(
        posting_service_module, "PeriodCloseRepository", _FakeLockedPeriodCloseRepository
    )

    service = PostingService(session=_FakeSession())  # type: ignore[arg-type]
    with pytest.raises(VErr):
        await service.post(
            transaction_type=TransactionType.AP_INVOICE,
            reference_id=uuid.uuid4(),
            posting_date=date(2026, 1, 15),  # inside the closed period above
            currency=Currency.USD,
            lines=[
                PostingLine(account_code="5000-EXP", debit=Decimal("100.00")),
                PostingLine(account_code="2000-AP", credit=Decimal("100.00")),
            ],
            actor_id="tester",
        )
