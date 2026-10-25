"""
app.services.approval_views
=============================
Pure definitions shared by the approval inbox API, repository and tests.

The inbox used to list only `pending` requests. Once a request was approved
it dropped out of every list, so an approved-but-not-yet-executed action
(or one whose execution failed) could never be found, executed or
reconciled again after a page reload. The named *views* below give every
lifecycle state a stable, queryable home without changing what the default
(`pending`) request returns.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, get_args

from app.core.exceptions import BaseAppException

ApprovalView = Literal[
    "pending",
    "awaiting_execution",
    "executing",
    "failed",
    "executed",
    "rejected",
    "approved",
    "all",
]
APPROVAL_VIEWS: tuple[str, ...] = get_args(ApprovalView)

# Views listed oldest-first (work queues); the rest are history, newest-first.
OLDEST_FIRST_VIEWS = frozenset({"pending", "awaiting_execution", "executing", "failed"})

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
EXECUTION_PENDING = "execution_pending"
EXECUTING = "executing"
EXECUTED = "executed"
FAILED = "failed"


def summarize_approval_counts(
    rows: Iterable[tuple[str, str, bool, int]],
) -> dict[str, int]:
    """Fold grouped (status, execution_status, has_action, count) rows into the
    inbox counters. `has_action` says whether the approval is executable."""
    counts = {"pending": 0, "awaiting_execution": 0, "executing": 0, "failed": 0}
    for status, execution_status, has_action, count in rows:
        if status == PENDING:
            counts["pending"] += count
        elif status == APPROVED and has_action:
            if execution_status == EXECUTION_PENDING:
                counts["awaiting_execution"] += count
            elif execution_status == EXECUTING:
                counts["executing"] += count
            elif execution_status == FAILED:
                counts["failed"] += count
    return counts


_GENERIC_EXECUTION_ERROR = (
    "Execution failed because of an unexpected internal error. Check the audit entry for this "
    "approval and reconcile the underlying document before retrying."
)


def public_execution_error(exc: Exception) -> str:
    """Text safe to store on the approval record and return to API readers.

    Business exceptions carry messages written for users. Anything else (a
    database or library error) may contain SQL, hostnames or parameters, so
    only a generic message is exposed; the full detail goes to the restricted
    server log and audit trail.
    """
    if isinstance(exc, BaseAppException):
        return exc.message[:1000]
    return _GENERIC_EXECUTION_ERROR
