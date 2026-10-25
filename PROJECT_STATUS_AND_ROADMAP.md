# Project Status and Roadmap

Review date: **2026-10-09**

## Current position

The repository is an existing finance platform with real backend domain services, repositories, agents, Pydantic contracts, PostgreSQL/Alembic support, and a React/Vite frontend. The current work focused on hardening and proving boundaries rather than replacing working finance logic.

## Completed in this hardening pass

- durable append-only audit log with database immutability trigger and hash-chain verification
- typed approval execution lifecycle with allowlisted commands and stable idempotency keys
- row locks and idempotent payment execution path
- server-authoritative role/permission resolution
- persisted refresh-token sessions with rotation and logout
- typed backend-generated agent catalog consumed by React
- centralized finance formatting helpers that preserve decimal strings without binary floating-point conversion
- Vendor Detail workspace using existing AP-priority/vendor APIs, with backend masking for bank coordinates
- non-idempotent browser mutations are not automatically replayed after token refresh unless an idempotency key is provided
- authentication bootstrap no longer trusts a cached client-side user before `/auth/me` confirmation
- premium enterprise application shell and workspace navigation
- private-route SEO directives (`noindex`, `nofollow`, robots disallow)
- SAP transport/mutation safety hardening and reconciliation-required states
- backend/frontend API separation with no browser-side SAP credentials
- app Dockerfiles, frontend Nginx image, and dependency-aware compose
- Playwright and accessibility test scaffolding
- API and frontend QA matrices

## Verified locally

- Python AST parsing passed for all inspected backend/service/repository/agent/schema/model/migration/test files.
- `python -m compileall -q app tests alembic` passed.
- 106 deterministic aging/AP-priority/SAP-mapping tests passed.
- Alembic offline migration generation to `0014_approval_idempotency_key` passed after correcting the sequence DDL.

The latest selected test cohort passed 106 tests in 1.24s. A global TypeScript syntax parse passed for 29 frontend/E2E source files; this is not equivalent to `tsc --noEmit` or browser QA.

## Environment blockers

The current execution environment does not contain the full development toolchain:

- `passlib` missing
- `tenacity` missing
- `ruff` missing
- `mypy` missing
- `bandit` missing
- `pip-audit` missing
- Docker CLI missing
- frontend `node_modules` missing
- npm registry access is unavailable, so frontend dependency installation could not complete

Because of these blockers, the full backend suite, browser tests, accessibility automation, dependency audits, and Docker build cannot honestly be marked passed here.

## High-priority product correctness gap

- **Multi-currency rollups are not production-safe yet.** Existing AR portfolio/customer and AP summary calculations sum document amounts without grouping by currency or FX conversion. Their summary response contracts do not expose per-currency totals, while the current UI defaults summary formatting to PKR. Until the environment enforces single-currency data or a proper functional-currency/FX design is implemented and tested, do not use those cross-currency rollups for financial decisions.

## Next controlled verification

1. Resolve the multi-currency aggregation blocker before enabling mixed-currency AP/AR data.
2. Install `requirements-dev.txt` in a clean environment.
3. Create a dedicated PostgreSQL test database and run the integration suite.
4. Install frontend dependencies and run typecheck, lint, unit/component tests, build, Playwright, and Axe.
5. Run Docker Compose build/start and health checks.
6. Execute `SAP_LIVE_VERIFICATION.md` against an approved SAP Business One test company.
7. Replace the process-local rate limiter with Redis-backed distributed enforcement before horizontal production scaling.
8. Add MFA/SSO if enterprise identity policy requires it.


## Current remediation update (2026-10-10)

Mixed-currency AR/AP aggregates now group by document currency and return explicit breakdowns; ambiguous flat totals are null rather than being reported under a guessed currency. Regression tests cover mixed currencies and Decimal precision. A backend-only, TLS-verified SAP read-only probe has been added; interactive sync now requires `agent:configure` and is restricted to vendor/customer master data. Current focused QA: 120 passed, 1 skipped; full suite/frontend/security/Docker/live SAP checks remain blocked. Production acceptance is pending; see `FINAL_QA_REPORT.md` and `REMAINING_WORK_AND_ACCEPTANCE.md`.
