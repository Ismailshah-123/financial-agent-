"""
app.core.client_ip
====================
Pure helpers (no framework imports) for the two inputs a rate limiter must
get right:

* **Who is the caller?**  Behind a reverse proxy every request arrives from
  the proxy's address, so keying a limiter on the TCP peer would put *all*
  users in one bucket. `X-Forwarded-For` is only trustworthy for the entries
  appended by proxies we operate, so the caller states how many trusted
  proxy hops sit in front of the app (`APP_TRUSTED_PROXY_HOPS`) and we take
  the address recorded by the outermost trusted hop. Anything the client put
  further left in the header is ignored. With zero hops (the default) the
  header is never consulted and cannot be spoofed.
* **What is being limited?**  Limits are scoped per route *shape*, not per
  concrete URL, so `/approval-requests/<uuid-1>/approve` and
  `/approval-requests/<uuid-2>/approve` share one bucket instead of each
  getting a fresh allowance.
"""

from __future__ import annotations

import ipaddress
import re

_UUID_SEGMENT = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_NUMERIC_SEGMENT = re.compile(r"^\d+$")


def client_ip(peer: str | None, forwarded_for: str | None, trusted_hops: int) -> str:
    """Return the best available client address for rate limiting."""
    fallback = peer or "unknown"
    if trusted_hops <= 0 or not forwarded_for:
        return fallback
    entries = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    if len(entries) < trusted_hops:
        # Fewer hops than configured: the header cannot be trusted as-is.
        return fallback
    candidate = entries[-trusted_hops]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return fallback


def rate_limit_scope(path: str) -> str:
    """Collapse identifier path segments so one route shape shares one bucket."""
    segments = []
    for segment in path.split("/"):
        if _UUID_SEGMENT.match(segment) or _NUMERIC_SEGMENT.match(segment):
            segments.append(":id")
        else:
            segments.append(segment)
    return "/".join(segments)
