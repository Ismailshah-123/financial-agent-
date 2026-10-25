"""Unit tests for approval inbox views, counters and error sanitisation."""

from __future__ import annotations

import pytest

from app.core.exceptions import ConflictError
from app.services.approval_views import (
    APPROVAL_VIEWS,
    OLDEST_FIRST_VIEWS,
    public_execution_error,
    summarize_approval_counts,
)


def test_default_listing_view_is_still_pending() -> None:
    assert "pending" in APPROVAL_VIEWS and APPROVAL_VIEWS[0] == "pending"


def test_every_work_queue_view_is_a_known_view() -> None:
    assert OLDEST_FIRST_VIEWS <= set(APPROVAL_VIEWS)


def test_summary_counts_only_executable_approved_requests() -> None:
    rows = [
        ("pending", "execution_pending", True, 4),
        ("pending", "not_applicable", False, 2),
        ("approved", "execution_pending", True, 3),
        ("approved", "not_applicable", False, 9),  # review-only: nothing to execute
        ("approved", "executing", True, 1),
        ("approved", "failed", True, 2),
        ("approved", "executed", True, 20),
        ("rejected", "execution_pending", True, 5),
    ]
    assert summarize_approval_counts(rows) == {
        "pending": 6,
        "awaiting_execution": 3,
        "executing": 1,
        "failed": 2,
    }


def test_summary_of_empty_inbox_is_all_zero() -> None:
    assert summarize_approval_counts([]) == {
        "pending": 0,
        "awaiting_execution": 0,
        "executing": 0,
        "failed": 0,
    }


def test_business_errors_keep_their_user_facing_message() -> None:
    assert public_execution_error(ConflictError("Invoice already paid.")) == "Invoice already paid."


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError('relation "payments" does not exist; SELECT * FROM payments WHERE id=$1'),
        ConnectionError("db-prod-01.internal:5432 refused"),
    ],
)
def test_unexpected_errors_never_leak_internal_text(exc: Exception) -> None:
    message = public_execution_error(exc)
    assert "SELECT" not in message and "internal:5432" not in message
    assert "reconcile" in message
