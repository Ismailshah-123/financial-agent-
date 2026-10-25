"""
app.core.middleware
====================
FastAPI/Starlette middleware stack, applied in app.main in this order
(outermost first):

    1. CorrelationIdMiddleware   — assigns/propagates a request id used by
                                    every log line and audit entry for that
                                    request (see app.core.logging).
    2. SecurityHeadersMiddleware — standard hardening headers (HSTS, nosniff,
                                    frame-deny, referrer-policy).
    3. RequestLoggingMiddleware  — structured access log with latency.
    4. RateLimitMiddleware       — sliding-window limiter held IN PROCESS
                                    MEMORY. It is correct for a single API
                                    worker only: with several workers or
                                    replicas each keeps its own counters, so
                                    the effective limit is multiplied. A
                                    Redis-backed limiter is required before
                                    scaling out (see REMAINING_WORK).

Exception-to-HTTP-response translation (turning `BaseAppException`
subclasses into JSON error bodies) is registered as FastAPI exception
handlers in app.main, not as middleware — that's the idiomatic FastAPI
pattern and keeps this file focused on cross-cutting request processing.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.client_ip import client_ip, rate_limit_scope
from app.core.config import settings
from app.core.constants import CORRELATION_ID_HEADER
from app.core.logging import bind_context, get_logger

logger = get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        correlation_id = request.headers.get(CORRELATION_ID_HEADER, str(uuid.uuid4()))
        bind_context(correlation_id)
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            client_ip=client_ip(
                request.client.host if request.client else None,
                request.headers.get("X-Forwarded-For"),
                settings.app.trusted_proxy_hops,
            ),
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Single-process fixed-window rate limiter with stricter sensitive limits.

    Development/test use stays dependency-free. Production should run with a
    distributed Redis-backed limiter before scaling beyond one worker.
    """

    def __init__(self, app, *, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[tuple[str, str], list[float]] = defaultdict(list)

    def _client_key(self, request: Request) -> str:
        # Never key on a client-supplied header such as X-API-Key: rotating its
        # value would hand an attacker a fresh allowance on every request
        # (including login attempts). Use the network address instead.
        return client_ip(
            request.client.host if request.client else None,
            request.headers.get("X-Forwarded-For"),
            settings.app.trusted_proxy_hops,
        )

    def _limit_for(self, request: Request) -> tuple[int, int]:
        path = request.url.path
        if path.endswith("/auth/login"):
            return 10, 300
        if path.endswith("/auth/refresh"):
            return 30, 300
        if path.startswith("/api/") and request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            if "/agents/" in path or "/approval-requests/" in path or "/payments" in path or "/sap" in path:
                return 30, 60
        return self.max_requests, self.window_seconds

    def _is_allowed(self, key: str, scope: str, limit: int, window: int) -> bool:
        now = time.time()
        window_start = now - window
        bucket_key = (key, scope)
        hits = [t for t in self._hits[bucket_key] if t > window_start]
        hits.append(now)
        self._hits[bucket_key] = hits
        if len(self._hits) > 10000:
            self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self.window_seconds}
        return len(hits) <= limit

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        limit, window = self._limit_for(request)
        if not self._is_allowed(
            self._client_key(request), rate_limit_scope(request.url.path), limit, window
        ):
            retry_after = max(1, window)
            return JSONResponse(
                status_code=429,
                content={
                    "error_code": "rate_limit_exceeded",
                    "message": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                    "details": {"limit": limit, "window_seconds": window},
                },
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
