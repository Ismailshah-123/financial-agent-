"""
app.services.report_currency
==============================
Pure (database-free, framework-free) policy for choosing the single
currency a General Ledger report is produced in. Kept separate from
`financial_reporting_service` so the rule is unit-testable without a
database and so the "never combine currencies" decision lives in one
small, auditable place.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.core.exceptions import ValidationError


def resolve_report_currency(available: Iterable[str], requested: str | None) -> str | None:
    """Pure. Decide which single currency a report is produced in.

    * An explicit request always wins (normalised to upper case); a
      currency with no postings simply yields an empty report.
    * Without a request, exactly one posted currency is selected
      automatically and an empty ledger window yields ``None``.
    * Without a request and with several posted currencies the call is
      refused: silently summing unlike currencies would be a wrong
      financial statement.
    """
    if requested is not None:
        code = requested.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValidationError(
                "currency must be a three-letter ISO 4217 code.",
                details={"currency": requested},
            )
        return code
    ordered = sorted({str(code).strip().upper() for code in available if code})
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    raise ValidationError(
        "The ledger contains posted entries in more than one currency for this period. "
        "Choose a currency; amounts in different currencies are never combined.",
        details={"available_currencies": ordered},
    )
