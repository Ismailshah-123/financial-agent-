# Security Review

Review date: **2026-10-09**

## Implemented controls

### Authentication

Password hashing uses bcrypt through Passlib. Access tokens are short-lived JWTs. Refresh tokens are now persisted as sessions, rotated on every successful refresh, and revocable through `POST /api/v1/auth/logout`.

### Authorization

Protected endpoints use server-side permission dependencies. The current role is resolved from the active database user, not trusted solely from browser-visible JWT claims.

### Sensitive vendor bank data

Vendor responses are normalized in the route layer. General `vendor:read` access does not disclose IBAN/SWIFT fields; the new `vendor:bank_details:read` permission is limited by the role map to Finance Director and Super Admin. The Vendor Detail UI also hides these fields for other roles, but the backend response masking is the security boundary. Regression tests were added; they could not be executed here because unit-test collection is blocked by missing Passlib/Tenacity dependencies.

### Token refresh and non-idempotent mutations

After a 401, safe read methods may be retried after successful refresh. A non-idempotent mutation is replayed only when the original request carries a non-empty `Idempotency-Key`. Otherwise, the session is renewed but the mutation is not replayed; the user is told to reload/reconcile the current record before trying again. This avoids implicit duplicate financial actions when the initial response is ambiguous.

### Approval security

Approval resolution and execution are separate. Execution is allowlisted and typed. The backend rechecks the command permission, current approval state, and command payload before executing.

### SAP safety

Read-only SAP calls may retry bounded transient transport failures. Mutating SAP calls are not automatically replayed after transport ambiguity or session expiry; the result is surfaced as requiring reconciliation because a previous mutation may already have committed.

### Secrets

No `.env`, certificate, private key, or credential file was found in the repository tree. Browser code contains no SAP, database, or LLM credentials. `.env.example` contains placeholders only. Production settings fail fast when the placeholder JWT or database password remains configured.

### HTTP hardening

Security headers are applied for content type sniffing, framing, referrer policy, HSTS, and browser capability restrictions. CORS no longer advertises credentialed cookies because the browser uses bearer headers.

### Rate limiting

A fixed-window in-process limiter is present with stricter limits for login, refresh, and high-risk write routes. This implementation is correct for one process. A distributed Redis-backed limiter is still required before scaling the API across multiple workers/pods.

### Error leakage

Known application exceptions return structured error responses. Unexpected exceptions return a generic 500 response while stack traces stay in server logs.

## Findings and remaining hardening

| Area | Status | Note |
|---|---|---|
| SQL injection | HARDENED | SQLAlchemy/query parameters used; no raw user-supplied SQL execution path identified. |
| IDOR/Broken object auth | NEEDS DOMAIN REVIEW | Endpoint RBAC is enforced; resource-level ownership/tenant isolation is still limited because the current data model is effectively single-tenant/default-tenant. |
| XSS | NEEDS BROWSER VERIFICATION | React escapes rendered strings, but a browser-based security test should still run after frontend dependencies are installed. |
| SSRF | NEEDS DOMAIN REVIEW | External SAP/LLM destinations come from server configuration; no general user-controlled URL fetch endpoint was identified. |
| Dependency vulnerabilities | BLOCKED_ENVIRONMENT | `pip-audit` and `npm audit` could not be run because the tools/dependencies are unavailable in the current environment. |
| Distributed rate limiting | BLOCKED_PRE_PRODUCTION | Current limiter is process-local. Must move to Redis before horizontal scaling. |
| MFA/SSO | NOT IMPLEMENTED | Security module documents this as future work; no fake implementation was added. |
| Independent failed-action audit sink | NOT IMPLEMENTED | Business transaction audit is durable on commit, but rollback can remove same-transaction failure records. |

## Repository secret scan

A source scan found configuration references only. No committed `.env`, PEM, key, or credential artifact was present.


## Current remediation update (2026-10-10)

The malformed `app/schemas/sap_status.py` module was replaced with explicit Pydantic contracts because it previously duplicated router source and did not define the model imported by the SAP router. The read-only verification endpoint has safe normalized states, correlation logging, bounded timeout and mandatory TLS validation; config now rejects SAP enabled with `SAP_VERIFY_SSL=false`. SAP synchronization requires `agent:configure`; the request schema and UI limit interactive sync to customer/vendor master data, disabling accounting-document/payment writes until a proper approval-bound execution and reconciliation workflow exists. Mock endpoint tests are present but skipped because `tenacity` cannot be installed in this environment. Existing open issues remain: resource/tenant isolation review, browser XSS verification, process-local rate limits before horizontal scale, MFA/SSO if required, and an independent rollback-resistant failure-audit sink.

## Pass 2 findings (2026-10-14)

| Area | Finding | Status |
|---|---|---|
| Rate limiting bypass | The limiter keyed on the client supplied `X-API-Key` header. Rotating the value defeated login throttling. | FIXED: keyed on network address with `APP_TRUSTED_PROXY_HOPS`; unit tested. |
| Rate limit scope | Limits were per concrete URL, so `/approval-requests/<id>/approve` got a new allowance for every id. | FIXED: scoped per route shape; unit tested. |
| Shared bucket behind a proxy | Behind nginx all users appeared as one address. | FIXED with the trusted hop setting. Keep the API port off the public network or clients could forge the header. |
| Cross currency GL reports | Reports summed unlike currencies. | FIXED, see `FINAL_QA_REPORT.md`. |
| Raw exception text in approval records | Returned to any reader with `approval_request:read`. | FIXED: generic text, detail in server log. |
| Token refresh race | Parallel 401s each refreshed; with rotating refresh tokens this logs the user out and can look like token theft. | FIXED in the client: one shared refresh. |
| Idle sessions | Tokens lived in the tab with no inactivity limit. | MITIGATED: configurable idle sign out (default 30 minutes). Tokens remain in `sessionStorage`; the CSP is the defence against script injection. HttpOnly cookies were not adopted because that changes the authentication architecture and could not be tested here. |
| Content Security Policy | None. | ADDED in nginx and `vercel.json`. NOT validated in a browser. |
| Container exposure | PostgreSQL, Redis and Qdrant were published on all interfaces with development passwords. | FIXED: bound to 127.0.0.1. |
| Container privileges | The web container ran nginx as root. | CHANGED to the unprivileged image on port 8080. Not built here. |
| First user in production | No supported way to create a user once registration is disabled. | ADDED `scripts/create_user.py`. |
| JWT secret strength | Only the placeholder value was rejected. | Staging and production now require 32 or more characters. |
| Not fixed | Process local limiter (single worker only); no MFA or SSO; audit failure evidence can be lost on rollback; no user administration endpoints; `npm audit` and `pip-audit` not run. | OPEN, listed in `docs/GO_LIVE_CHECKLIST.md` section E. |
