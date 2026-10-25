# Final Technical Audit

Audit date: **2026-10-09**

## Repository coverage

Automated source inventory and AST validation covered:

- 29 service modules
- 22 repository modules
- 38 agent modules
- 27 schema modules
- 22 database model modules
- 14 Alembic migrations
- 82 FastAPI route decorators in the current working tree (81 in the historical source inventory)
- 27 frontend source files
- 25 unit-test modules
- 19 integration-test modules

No Git metadata was present in the uploaded ZIP, so Git status/history could not be audited.

## Backend

| Area | Assessment | Notes |
|---|---|---|
| Framework/version | READY | FastAPI + Pydantic v2 codebase; dependency ranges are defined in `requirements.txt`. |
| Python | READY | Project requires Python >=3.11. |
| Database | READY WITH EXTERNAL DB | PostgreSQL via SQLAlchemy async runtime and psycopg2/Alembic migration path. |
| Migration state | READY | Single Alembic head `0014_approval_idempotency_key`; offline SQL generation passes. |
| API routes | INVENTORIED / NEEDS INTEGRATION VERIFICATION | Current source has 82 route decorators; endpoint/integration tests remain blocked by missing dependencies/database. |
| Authentication | NEEDS LIVE/INTEGRATION VERIFICATION | JWT access tokens, persisted refresh sessions, rotation, logout; full auth tests blocked by missing Passlib in this environment. |
| RBAC | READY IN CODE / NEEDS INTEGRATION VERIFICATION | Backend rereads active user role and derives permissions server-side. |
| Agent architecture | READY | Base agent + specialized agents with Pydantic decision envelopes and catalog endpoint. |
| Services/repositories | READY | Domain logic remains backend-owned; row-locking added for financial mutations and approvals. |
| Error handling | READY | Structured application errors plus generic internal-error boundary. |
| Auditability | NEEDS HARDENING | Durable append-only audit chain is implemented. Independent rollback-resistant failure sink remains future work. |
| Currency aggregation | PATCHED / FOCUSED REGRESSION VERIFIED | AR and AP summary contracts group amounts by document currency; mixed-currency flat scalar totals are null and `currency_balances` carries explicit Decimal amounts. No FX conversion is invented. Full integration QA remains blocked. |
| Background jobs | READY | Celery worker and task module are present. |
| Caching | PARTIALLY IMPLEMENTED | Redis configured; no broad mutable finance-data cache is introduced. |
| Rate limiting | NEEDS HARDENING FOR HORIZONTAL SCALE | In-process fixed-window limiter with sensitive endpoint limits; Redis-backed distributed enforcement still required before multi-worker scale. |
| External dependencies | BLOCKED BY ENVIRONMENT | Full clean install not possible in this sandbox. |
| SAP integration | NEEDS LIVE VERIFICATION | Service Layer client, B1SESSION contract check, mapping, error normalization, safe read retry, mutation ambiguity handling implemented. |
| LLM providers | READY IN CODE / NEEDS PROVIDER TEST | Groq, Anthropic, OpenAI, Gemini configuration exists; runtime provider verification requires credentials. |
| Configuration | READY | Pydantic settings centralize configuration; production blocks default JWT/database secrets, debug, wildcard CORS, and public registration. Broker defaults contain no embedded credentials. |
| Technical debt | NEEDS HARDENING | See remaining blockers below, especially frontend JS migration, MFA/SSO, distributed rate limiting, and independent failed-event audit. |

## Frontend

| Area | Assessment | Notes |
|---|---|---|
| Framework | READY | React + Vite. |
| TypeScript | PARTIALLY IMPLEMENTED | Core app, API client, auth, formatters, shared types, Vite entry, and shell use TypeScript. Existing feature pages/components remain JS/JSX and are not strict-typechecked. |
| Routing | READY | History API routing with auth/permission guards. |
| State management | READY | React state/hooks; no unnecessary global state dependency. |
| API client | READY | Centralized typed client, timeout, normalized errors, correlation IDs, refresh retry, request cancellation. |
| Authentication flow | NEEDS E2E VERIFICATION | Session storage and `/auth/me` server identity flow are implemented. |
| Token handling | NEEDS SECURITY BROWSER REVIEW | Access/refresh tokens are stored in sessionStorage; no credentials are exposed through Vite env. |
| Loading/error/empty states | IMPLEMENTED / NEEDS BROWSER VERIFICATION | Shared components and page-level states exist; browser rendering and state transitions are not verified in this environment. |
| Responsive behavior | IMPLEMENTED / NEEDS BROWSER VERIFICATION | Responsive CSS/mobile navigation exist; each page remains unverified at real browser viewports because Playwright dependencies are unavailable. |
| Accessibility | TEST DEFINED / BLOCKED | Axe/Playwright suite exists; dependencies unavailable in current environment. |
| SEO | READY FOR PRIVATE APP | Authenticated SPA has `noindex,nofollow,noarchive`, robots disallow, manifest, and favicon. No public landing page currently exists. |
| Design system | READY | Shared UI components and CSS tokens; feature page CSS still uses some local class conventions. |

## QA

| Capability | Assessment |
|---|---|
| Backend unit tests | PARTIALLY VERIFIED |
| Backend integration tests | BLOCKED BY ENVIRONMENT |
| Frontend unit/component tests | BLOCKED BY ENVIRONMENT |
| E2E | DEFINED / BLOCKED BY ENVIRONMENT |
| API contract inventory | READY |
| Migration SQL generation | VERIFIED |
| Security scans | BLOCKED BY MISSING TOOLS |
| Dependency audits | BLOCKED BY MISSING TOOLS / NETWORK |
| Docker verification | BLOCKED BY MISSING DOCKER CLI |
| CI | IMPLEMENTED |

## SAP

Implemented code paths are server-side and secret-safe. Mutation retries are deliberately conservative: an ambiguous POST/PATCH/DELETE is not replayed automatically. The system exposes reconciliation-required behavior instead.

Live SAP compatibility is **not verified** in this environment.

## Final classifications

- **READY**: architecture, route inventory, backend-owned finance truth, approval command boundary, migration chain, SAP safety boundary, private frontend API boundary.
- **NEEDS HARDENING**: distributed rate limiting, independent failure-event audit persistence, complete TypeScript migration, MFA/SSO if required by enterprise policy.
- **PARTIALLY IMPLEMENTED**: frontend strict TypeScript coverage, production-grade observability/dependency verification.
- **NOT IMPLEMENTED**: live SAP verification, MFA/SSO, public SEO landing/product page.
- **BLOCKED BY EXTERNAL ENVIRONMENT**: full dependency install, complete automated suite, frontend browser/a11y runs, live Docker validation, live SAP test.


## Latest hardening changes (2026-10-09)

- Added the backend-driven Vendor Detail workspace using the existing AP-priority/vendor APIs and vendor read API; no new fake endpoint or local financial calculation was introduced.
- Restricted bank-account coordinates on every vendor response unless the role has `vendor:bank_details:read`; the current role map grants it only to Finance Director and Super Admin.
- Changed client 401 refresh handling so read-only requests can replay, while financial mutations are replayed only with a non-empty idempotency key.
- Changed auth bootstrap to render no cached user as authenticated until `/auth/me` confirms server identity.
- Replaced float-based monetary formatting with string/BigInt decimal rounding and changed missing/invalid financial values to `—`.
- Added regression tests and expanded frontend formatter/API tests; the new backend tests are source-compiled but could not run because required dependencies are missing.


## Financial correctness finding — currency aggregation (historical finding, patched below)

The initial source inventory found cross-currency addition without FX normalization. The current working tree now groups AR/AP customer/vendor/portfolio balances by document currency, returns null for misleading mixed-currency scalar amount fields, and updates critical summary UI paths to present the grouped values. No functional-currency/FX engine was retrofitted. The focused regression and response-contract cohort passes; clean database/full-suite verification is still blocked by environment dependencies.


## Current remediation addendum (2026-10-10)

This addendum supersedes the earlier currency finding: AR aging/customer and AP portfolio/vendor aggregators group document amounts by currency, with exact Decimal totals in `currency_balances`. Flat scalar amounts are null when multiple currencies are in scope; no FX engine was invented. Dashboard, Receivables, Customer Detail, Payables and Vendor Detail use those per-currency balances. The focused pure calculation/mapping/response-contract cohort passes **120 tests**, with the SAP API endpoint test module skipped due the missing `tenacity` dependency.

Source inspection also found `app/schemas/sap_status.py` duplicated router code and did not provide the SAP status response model imported by its router. The model module is repaired and a bounded, read-only, TLS-verified `POST /api/v1/sap/verify` endpoint/UI has been added. The interactive SAP sync route requires `agent:configure` and accepts only vendor/customer master records; financial-document/payment write methods are not available through that request contract.

Current environment blockers remain: `pytest -q` cannot load integration fixtures without `asyncpg`; dependencies cannot be installed because registry DNS/network access fails; real `tsc`, lint, Vitest/build/npm audit, Python security tools, Docker, online migrations, Playwright/Axe and live SAP checks remain unverified. Production readiness is **NOT VERIFIED**.
