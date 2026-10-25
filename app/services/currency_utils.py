"""Currency normalization for financial summaries; does not perform FX conversion."""

from __future__ import annotations

import re
from enum import Enum

from app.core.constants import Currency

SUPPORTED_CURRENCY_CODES = frozenset(currency.value for currency in Currency)


def normalize_currency_code(value: object) -> str:
    """Return a known domain currency or an explicit unknown-code group label."""
    if isinstance(value, Enum):
        value = value.value
    raw = str(value or "").strip().upper()
    if not raw:
        return "UNSPECIFIED"
    if raw in SUPPORTED_CURRENCY_CODES:
        return raw
    safe = re.sub(r"[^A-Z0-9_-]", "_", raw)[:32] or "UNSPECIFIED"
    return f"UNSUPPORTED:{safe}"
