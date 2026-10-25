"""Unit tests for the rate limiter's caller identification and scoping.

Regression for two defects: (1) a client-controlled `X-API-Key` header was used
as the limiter key, so rotating it bypassed every limit including login
attempts; (2) limits were scoped per concrete URL, so every UUID in a path
received its own fresh allowance.
"""

from __future__ import annotations

import pytest

from app.core.client_ip import client_ip, rate_limit_scope


def test_forwarded_header_is_ignored_without_trusted_proxies() -> None:
    assert client_ip("10.0.0.5", "203.0.113.9", 0) == "10.0.0.5"


def test_single_trusted_proxy_uses_the_address_it_appended() -> None:
    assert client_ip("172.18.0.3", "203.0.113.9", 1) == "203.0.113.9"


def test_client_supplied_leading_entries_cannot_spoof_the_address() -> None:
    # The attacker prepends 1.1.1.1; nginx appends the real peer, 198.51.100.7.
    assert client_ip("172.18.0.3", "1.1.1.1, 198.51.100.7", 1) == "198.51.100.7"


def test_two_trusted_hops_skip_the_inner_proxy() -> None:
    assert client_ip("172.18.0.3", "203.0.113.9, 10.1.1.1", 2) == "203.0.113.9"


def test_missing_or_short_header_falls_back_to_the_peer() -> None:
    assert client_ip("172.18.0.3", None, 1) == "172.18.0.3"
    assert client_ip("172.18.0.3", "", 1) == "172.18.0.3"
    assert client_ip("172.18.0.3", "203.0.113.9", 2) == "172.18.0.3"


def test_garbage_in_the_header_falls_back_to_the_peer() -> None:
    assert client_ip("172.18.0.3", "not-an-ip", 1) == "172.18.0.3"


def test_ipv6_is_normalised() -> None:
    assert client_ip("::1", "2001:DB8:0:0:0:0:0:1", 1) == "2001:db8::1"


def test_unknown_peer_is_labelled() -> None:
    assert client_ip(None, None, 0) == "unknown"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "/api/v1/approval-requests/3f2b8c1e-5d4a-4b7e-9a10-0c2d3e4f5a6b/approve",
            "/api/v1/approval-requests/:id/approve",
        ),
        ("/api/v1/invoices/42/approve", "/api/v1/invoices/:id/approve"),
        ("/api/v1/auth/login", "/api/v1/auth/login"),
        ("/api/v1/aging/summary", "/api/v1/aging/summary"),
    ],
)
def test_rate_limit_scope_collapses_identifiers(path: str, expected: str) -> None:
    assert rate_limit_scope(path) == expected


def test_two_ids_share_one_scope() -> None:
    a = rate_limit_scope("/api/v1/payments/3f2b8c1e-5d4a-4b7e-9a10-0c2d3e4f5a6b/execute")
    b = rate_limit_scope("/api/v1/payments/aaaaaaaa-5d4a-4b7e-9a10-0c2d3e4f5a6b/execute")
    assert a == b
