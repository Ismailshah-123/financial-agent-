# Remaining Work and Production Acceptance

Review date: **2026-10-10**

## Status

**NOT PRODUCTION READY.** The repository contains a substantial finance application and this hardening pass added targeted safety and usability improvements, but full project QA and several finance/integration risks remain unresolved. This status is intentional: blocked checks are not counted as passing.

## Existing capabilities found in the supplied repository

- FastAPI backend with 82 route decorators in the current working tree (81 in the historical inventory), Pydantic request/response contracts, domain services, repositories, and specialized finance agents.
- PostgreSQL/SQLAlchemy async persistence and a 14-migration Alembic chain; one head is present.
- Accounts Payable, Accounts Receivable/aging, collections, payment prioritization, reporting, tax, treasury, budget planning, fraud/compliance, reconciliation, period-close and finance-director agent/service foundations.
- Persisted refresh sessions, server-side role-derived authorization, an allowlisted approval execution boundary, durable append-only audit-chain implementation, and SAP Service Layer integration foundations.
- React/Vite frontend workspaces for Dashboard, Receivables, Customer Detail, Payables, Vendor Detail, Approval Inbox, AI Agent Center, Reports, SAP Integration, Audit Center, Settings and Login.
- API/technical/security/SAP documentation, unit and integration test suites, CI configuration, Dockerfiles and Compose configuration.

These are source-level inventory findings, not proof that every route or workflow passed an end-to-end test.

## Changes made in this delivery

- Added a backend-driven Vendor Detail workspace consuming the existing AP-priority/vendor API contracts, with exposure, obligations, profile fields and partial/error/loading states.
- Added the `vendor:bank_details:read` role permission. Vendor responses now omit IBAN/SWIFT unless the server-side role map explicitly grants that permission; the new UI follows the same permission.
- Prevented automatic replay of non-idempotent API mutations after a 401 refresh unless the original request supplies a non-empty idempotency key.
- Changed auth bootstrap so cached browser user data is not treated as proof of an authenticated identity before `/auth/me` succeeds.
- Reworked monetary display formatting to round decimal strings using decimal-string/BigInt logic, avoid float conversion for money, and display missing or invalid values as `—` rather than silently showing zero.
- Removed money-to-Number conversions from the Receivables and Customer Detail overdue KPIs, fixed date-input defaults to local calendar dates, and improved dashboard permission states.
- Expanded Payables search/filter/pagination/error states, AppShell approval/user controls, and responsive detail styling.
- Added regression tests and updated the API, security, technical-audit, QA and remaining-work documentation.

## Historical baseline verification before the 2026-10-10 remediation

| Check | Result |
|---|---|
| `python -m compileall -q app tests alembic` | PASS, exit 0 |
| Selected aging/AP-priority/SAP-mapper tests | Historical baseline PASS, 106 passed in 1.26s before the current remediation cohort |
| `alembic heads` | PASS, `0014_approval_idempotency_key (head)` |
| `alembic upgrade head --sql` | PASS, 775 lines of offline SQL generated; online migration not tested |
| Global TypeScript syntax parse | PASS, 29 frontend/E2E files, 0 parse diagnostics |
| Targeted strict TypeScript check | PASS with temporary minimal React/Vite declaration stubs for the app shell, API/auth/formatters, and Vendor Detail; not a substitute for the project typecheck |
| Isolated formatter/retry helper cases | PASS, 13 of 13 manually executed Node cases; not Vitest |

## Blocking or incomplete work

### High-priority financial correctness

The cross-currency aggregation defect identified in the initial audit has been patched in the current working tree: AR and AP totals are grouped by document currency, mixed-currency scalar amount fields are null, and the currency breakdown carries exact Decimal amounts. Regression coverage passes in the focused local suite. Full database/integration QA is still required before production acceptance.

### Full automated QA

- Full unit suite is blocked during collection because `passlib` and `tenacity` are missing in the current environment.
- Full pytest/integration collection is blocked because `asyncpg` is missing. A real PostgreSQL test database was not available.
- Standard frontend typecheck is blocked by missing `vite/client` types and dependencies. ESLint, Vitest, Vite build and Playwright/Axe are not installed locally.
- npm audit is blocked because there is no lockfile and registry access is unavailable; no dependency vulnerability result is available.
- Ruff, Black, MyPy, Bandit and pip-audit executables are missing.
- Docker CLI is missing, so container builds/startup/health checks were not executed.
- Browser responsiveness, accessibility and E2E journeys have not been observed in a real browser.

### External integration and scaling

- Live SAP Business One authentication, read, mapping, synchronization, reconciliation and controlled write checks require an approved SAP test tenant/database and credentials; no live SAP verification was performed.
- Online Alembic migrations and PostgreSQL transaction/integration behavior remain unverified here.
- Rate limiting is process-local; use distributed enforcement (for example Redis-backed) before horizontal production scaling.
- MFA/SSO are not implemented; add them if required by the enterprise identity policy.
- Failed-action audit events that occur within a rolled-back business transaction do not yet have an independent rollback-resistant sink.
- Some capabilities are currently exposed through AI Agent Center/service/API foundations rather than dedicated domain workspaces; evaluate dedicated Tax, Treasury, Budget, Reconciliation and Compliance pages against product scope before claiming full workflow coverage.

## Required production acceptance gates

1. Re-run the added mixed-currency AR/AP regression tests as part of the full clean dependency/database acceptance suite.
2. Install declared Python dependencies in a clean environment; run the complete unit and integration suites against PostgreSQL, including all RBAC and new vendor-privacy tests.
3. Install frontend dependencies, create and commit a lockfile, and pass real `tsc`, lint/format, Vitest and Vite build checks.
4. Run Playwright journeys and Axe accessibility tests at desktop, tablet and mobile viewports, including role boundaries and read-only/controlled mutations.
5. Run Ruff/Black/MyPy/Bandit/pip-audit/npm audit and remediate or document real findings.
6. Build and start Docker Compose from a clean environment; confirm PostgreSQL migrations and health/readiness checks.
7. Complete controlled live SAP Business One verification using `SAP_LIVE_VERIFICATION.md`, including mutation ambiguity, duplicate prevention and audit/reconciliation behavior.
8. Re-run all checks from a clean environment and replace this report with actual command output.

Until those gates pass, suitable status wording is **“hardened implementation with partial local verification; production acceptance pending”**, not “fully production ready.”


## Current remediation update — 2026-10-10

### Completed targeted changes

- **AR/AP currency correctness:** normalized document currency and grouped AR invoice/customer/portfolio and AP obligation/vendor/portfolio totals by currency. The backend does not invent FX conversion. Mixed-currency scalar amount fields are null; `currency_balances` contains the precise Decimal totals. Customer credit limits apply only to the matching default currency. Missing/unrecognized currency codes are explicit.
- **Frontend:** Dashboard, Receivables, Customer Detail, Payables and Vendor Detail read currency groups from the backend and do not silently format a mixed-currency total as PKR.
- **SAP:** repaired the malformed status-schema module; added secret-safe configuration status and `POST /api/v1/sap/verify` read-only probe with bounded timeout, TLS validation, safe status/error classification and correlation ID. SAP sync route now requires `agent:configure` and accepts only customer/vendor master data; document/payment writes remain gated.
- **Focused QA:** compile passes, and the focused pure-calculation/mapping/response-contract cohort currently reports **120 passed, 1 skipped**. The skipped SAP endpoint mock module requires missing `tenacity`.

### Remaining acceptance blockers

- Full pytest is blocked at integration fixture import by missing `asyncpg`; additional unit tests require `passlib` and `tenacity`. Registry DNS/network access prevented installing missing packages.
- Frontend typecheck fails with missing `vite/client`; ESLint, Vitest and Vite build are not installed. No `package-lock.json` exists and npm audit is blocked. Playwright/Axe/browser viewports remain unverified.
- Ruff, Black, MyPy, Bandit, pip-audit and Docker CLI are unavailable. Online PostgreSQL migrations, real PostgreSQL transactions and clean Docker startup were not run.
- SAP read-only mocked tests could not run due missing `tenacity`; no approved live SAP tenant/credentials were available. No live integration, synchronization or write test is claimed.
- Process-local rate limiting needs distributed enforcement before horizontal scaling; MFA/SSO remains unimplemented if required by policy; failed audit events within rolled-back transactions still lack an independent sink; tenant/object-level access requires further review.

Production readiness remains **NOT ACCEPTED**; use status wording **“hardened implementation with partial local verification; production acceptance pending.”**

## Update 2026-10-14 (pass 2)

### Closed in this pass

- General Ledger reports are single currency, with an explicit currency choice (financial correctness item left open by pass 1).
- Rate limiter bypass and proxy address handling.
- Approval inbox lifecycle (approved, executing, failed and executed items stay reachable) and exact counters.
- Production user provisioning (`scripts/create_user.py`).
- Frontend: real URLs, shared token refresh, cancellation, typed UI kit, accessible dialogs, rewritten Receivables, Approvals, Reports, Audit, Settings, SAP and Overview pages, CSP and hardened nginx, lint configuration, rewritten browser tests.

### Still open, in priority order

1. Run the gates in `docs/GO_LIVE_CHECKLIST.md` section A and fix whatever they reveal. Expect small fixes: Black formatting, any pinned frontend version that does not exist on the registry, and issues that only real React types or a real browser expose.
2. Generate and commit `frontend/package-lock.json`.
3. Live SAP verification in an approved test company (section F).
4. Shared (Redis backed) rate limiter before running more than one API worker.
5. Independent durable record of failed business actions (audit evidence can be rolled back with the transaction).
6. MFA or SSO if your enterprise identity policy requires it.
7. A user administration screen (deactivate, reset password, change role).
8. Dedicated workspaces for tax, treasury, budgets, bank reconciliation, compliance and period close. Their backend endpoints exist but several lack list endpoints, so building screens needs small backend additions first.
9. Make audit chain verification incremental for large logs.
