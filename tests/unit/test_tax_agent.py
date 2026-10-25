"""
Unit tests for TaxAgent's deterministic pieces: the rate-matching rule,
the withholding-code lookup table, the summary builder, and the
JSON-parsing helper. These take plain values/dataclasses and return
plain values — no DB, no LLM, no event loop — same scope as
test_accounts_payable_agent.py.

The full `_execute` workflow (DB + LLM integrated: fetching the
invoice/vendor, calling TaxCalculationService, calling the LLM
classifier) is exercised by integration tests instead, once one exists
for this agent — see tests/integration/test_withholding_tax.py for the
deterministic withholding math this agent's recommendation ultimately
calls into.
"""

from __future__ import annotations

from decimal import Decimal

from app.agents.tax.agent import (
    _WITHHOLDING_CODE_MAP,
    _build_summary,
    _match_rate_to_active_codes,
    _parse_llm_json,
)
from app.db.models.enums import FilerStatus
from app.db.models.tax_code import TaxCode
from app.services.tax_service import TaxCalculationResult


def _tax_code(code: str, rate_percent: str) -> TaxCode:
    return TaxCode(
        code=code,
        name=code,
        tax_type="sales_tax",
        jurisdiction="PK-FEDERAL",
        rate_percent=Decimal(rate_percent),
    )


_ACTIVE_CODES = [
    _tax_code("PK-GST-STD", "18.000"),
    _tax_code("PK-SRB-SERVICES-STD", "13.000"),
]


def test_rate_within_tolerance_matches() -> None:
    matched = _match_rate_to_active_codes(Decimal("18.000"), _ACTIVE_CODES)
    assert matched is not None
    assert matched.code == "PK-GST-STD"


def test_rate_just_inside_tolerance_matches() -> None:
    # Tolerance is 0.05 percentage points — 18.04 should still match 18.000.
    matched = _match_rate_to_active_codes(Decimal("18.04"), _ACTIVE_CODES)
    assert matched is not None
    assert matched.code == "PK-GST-STD"


def test_rate_outside_tolerance_does_not_match() -> None:
    matched = _match_rate_to_active_codes(Decimal("17.5"), _ACTIVE_CODES)
    assert matched is None


def test_rate_matching_no_active_codes_returns_none() -> None:
    assert _match_rate_to_active_codes(Decimal("18.000"), []) is None


def test_withholding_code_map_covers_all_four_combinations() -> None:
    for filer_status in (FilerStatus.FILER, FilerStatus.NON_FILER):
        for category in ("goods", "services"):
            assert (filer_status, category) in _WITHHOLDING_CODE_MAP


def test_withholding_code_map_matches_seeded_migration_codes() -> None:
    # Mirrors alembic/versions/0005_tax_codes.py exactly — if that seed
    # data changes, this test (and the map) must change with it.
    assert _WITHHOLDING_CODE_MAP[(FilerStatus.FILER, "goods")] == "PK-WHT-153-GOODS-FILER"
    assert (
        _WITHHOLDING_CODE_MAP[(FilerStatus.NON_FILER, "goods")] == "PK-WHT-153-GOODS-NONFILER"
    )
    assert (
        _WITHHOLDING_CODE_MAP[(FilerStatus.FILER, "services")]
        == "PK-WHT-153-SERVICES-FILER"
    )
    assert (
        _WITHHOLDING_CODE_MAP[(FilerStatus.NON_FILER, "services")]
        == "PK-WHT-153-SERVICES-NONFILER"
    )


def test_summary_prioritizes_sales_tax_anomaly() -> None:
    summary = _build_summary(
        sales_tax_anomaly=True,
        withholding_result=None,
        needs_manual_categorization=True,  # even if also true, anomaly wins
    )
    assert "does not match" in summary


def test_summary_reports_withholding_recommendation() -> None:
    result = TaxCalculationResult(
        tax_code="PK-WHT-153-GOODS-FILER",
        tax_type="withholding_tax",
        rate_percent=Decimal("4.000"),
        base_amount=Decimal("11800.00"),
        tax_amount=Decimal("472.00"),
    )
    summary = _build_summary(
        sales_tax_anomaly=False, withholding_result=result, needs_manual_categorization=False
    )
    assert "472.00" in summary
    assert "PK-WHT-153-GOODS-FILER" in summary


def test_summary_reports_manual_categorization_needed() -> None:
    summary = _build_summary(
        sales_tax_anomaly=False, withholding_result=None, needs_manual_categorization=True
    )
    assert "manual" in summary.lower()


def test_summary_no_anomaly_no_withholding() -> None:
    summary = _build_summary(
        sales_tax_anomaly=False, withholding_result=None, needs_manual_categorization=False
    )
    assert "no withholding applicable" in summary.lower()


def test_parse_llm_json_handles_plain_json() -> None:
    result = _parse_llm_json('{"category": "goods", "confidence": 0.9}')
    assert result == {"category": "goods", "confidence": 0.9}


def test_parse_llm_json_strips_markdown_code_fence() -> None:
    raw = '```json\n{"category": "services"}\n```'
    assert _parse_llm_json(raw) == {"category": "services"}


def test_parse_llm_json_returns_none_on_garbage() -> None:
    assert _parse_llm_json("not json at all") is None
