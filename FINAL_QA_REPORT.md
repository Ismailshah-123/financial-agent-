# Final QA Report

Date: **2026-10-10**

## Historical uploaded-package baseline before current remediation (2026-10-09)

This historical baseline records verification before the current currency/SAP changes. Its counts are superseded by the 2026-10-10 results below. The repository contains no Git metadata, so changes are tracked against the supplied ZIP rather than a recoverable branch/commit.

| Check | Actual result | Evidence / limitation |
|---|---|---|
| `python -m compileall -q app tests alembic` | **PASS, exit 0** | All backend/tests/migration Python modules compile. |
| Selected deterministic unit tests | **Historical baseline: 106 passed in 1.26s** | `tests/unit/test_aging_calculations.py`, `test_ap_priority_calculations.py`, `test_sap_document_mappers.py`, `test_sap_mappers.py`. |
| Full `tests/unit` collection | **BLOCKED** | New/current environment could not import required `passlib` and `tenacity`; newly added bank-field privacy tests therefore were not executed. |
| Full `python -m pytest -q` | **BLOCKED** | Integration `conftest.py` cannot import required `asyncpg`. |
| `alembic heads` | **PASS** | `0014_approval_idempotency_key (head)`. |
| `alembic upgrade head --sql` | **PASS** | Offline SQL generated successfully; 775 lines. This is not proof of online PostgreSQL migration execution. |
| Frontend JS/TS syntax parse | **PASS: 29 files, 0 parse diagnostics** | Parsed with the installed global TypeScript parser. This is syntax-only, not a full type check. |
| Targeted strict TypeScript check | **PASS using temporary React/Vite stubs** | `App.tsx`, auth/API/formatters/types, `AppShell.tsx`, and `VendorDetail.tsx` passed `tsc` with temporary minimal declarations. This is supplementary only and does not replace the real Vite/React project typecheck. |
| Isolated frontend logic checks | **PASS: 13/13 cases** | Executed the decimal formatter and safe-refresh-replay helpers directly with Node after TypeScript transpilation; these were not Vitest tests. |
| `npm run typecheck` | **BLOCKED** | `TS2688: Cannot find type definition file for 'vite/client'` because dependencies are not installed. |
| `npm run lint` | **BLOCKED** | ESLint is not installed. |
| `npm test` | **BLOCKED** | Vitest is not installed. |
| `npm run build` | **BLOCKED** | Vite is not installed. |
| Playwright / Axe E2E | **BLOCKED** | Local Playwright/Axe dependencies are unavailable; no browser journey or accessibility result is claimed. |
| `npm audit --audit-level=high` | **BLOCKED** | No `package-lock.json`; audit requires a lockfile, and registry/network access is unavailable. |
| Ruff, Black, MyPy, Bandit, pip-audit | **BLOCKED** | The commands are not installed in the current environment. |
| Docker Compose build/start | **BLOCKED** | Docker CLI is not installed. |
| Live SAP Business One verification | **BLOCKED_EXTERNAL** | No approved SAP tenant, CompanyDB, endpoint or credentials were supplied. No live connectivity or posting claim is made. |
| Multi-currency rollups | **HIGH-PRIORITY FINANCIAL CORRECTNESS GAP** | AR/AP summary calculations sum values from documents without currency grouping or FX conversion, while summary APIs omit currency breakdowns. Safe only under a verified single-currency data constraint, which is not yet enforced/verified. |

The attempted dependency installation could not resolve packages in this sandbox because package registry access is unavailable. The source and unit tests were not weakened or removed to make the blocked suites appear green.

## Executive result

The initial uploaded-package hardening pass was source-validated but not fully production-verified. The current working-tree result is reported in the 2026-10-10 addendum below.

At this baseline, the selected finance/SAP calculation and mapping subset had **106 tests passed**. The current remediation test count and evidence are recorded in the working-tree verification addendum below. The complete backend suite is correctly configured to discover both unit and PostgreSQL integration tests, but it cannot collect here because the sandbox is missing the repository's declared `asyncpg` dependency. Frontend browser verification is blocked by unavailable npm dependencies/network, security tooling is absent, Docker is unavailable, and no live SAP Business One environment or controlled credentials were supplied.

No fake SAP connection, fake finance KPI, fake execution result, or fake test pass has been introduced or reported.

## Backend verification

### Compile / syntax

Command:

```text
python -m compileall -q app frontend tests alembic
```

Result: **PASS / exit 0**.

All inspected backend Python modules for services, repositories, agents, schemas, models, migrations, API routes, workers, and tests also passed AST parsing during the repository audit.

### Complete pytest suite

The default pytest discovery is configured for both:

```text
tests/unit
tests/integration
```

Command:

```text
python -m pytest -v
```

Result: **BLOCKED / exit 4 during collection**.

Exact blocker:

```text
ModuleNotFoundError: No module named 'asyncpg'
```

The failure occurs while loading `tests/integration/conftest.py`, which imports the PostgreSQL-backed application database engine.

No integration test was deleted or bypassed to avoid this result.

### Coverage command

Command:

```text
python -m pytest --cov=app --cov-report=term-missing -q
```

Result: **BLOCKED / exit 4 during collection** for the same missing `asyncpg` dependency.

### Deterministic finance/SAP subset

Command:

```text
python -m pytest -q tests/unit/test_aging_calculations.py tests/unit/test_ap_priority_calculations.py tests/unit/test_sap_document_mappers.py tests/unit/test_sap_mappers.py
```

Result: **PASS / exit 0**.

Exact result from the final run:

```text
106 passed in 1.87s (historical baseline run, before the current remediation cohort)
```

The coverage plugin reported **16% total application coverage for this subset**. That number is not a full-project coverage measurement and is not being represented as one.

## Migration verification

Command:

```text
alembic heads
```

Result: **PASS / exit 0**.

Head:

```text
0014_approval_idempotency_key
```

Command:

```text
alembic upgrade head --sql
```

Result: **PASS / exit 0**.

The offline SQL generation includes the durable audit tables, user-session migration, and the approval execution idempotency-key migration.

Online migration execution was not possible because no PostgreSQL server or Docker CLI is available in the sandbox.

## Dependency consistency

Command:

```text
python -m pip check
```

Result: **FAIL / exit 1 in the sandbox environment**.

Reported global environment conflict:

```text
moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.3.0.
```

This is outside the repository's declared dependency set and is not a package conflict introduced by this hardening pass.

The repository itself declares the missing runtime/test dependencies, including `asyncpg`, `passlib[bcrypt]`, and `tenacity`, in `requirements.txt`.

## Static analysis

The following commands were attempted but their executables are not installed in the current sandbox:

```text
ruff check .
black --check app tests alembic
mypy app
bandit -r app -x tests
pip-audit -r requirements.txt
```

Each returned **exit 127 / command not found**.

The tools remain declared in `requirements-dev.txt` and in CI.

## Frontend verification

The React/Vite application is source-complete for the current authenticated workspaces and has typed API/auth/formatting infrastructure, route guards, centralized UI primitives, Vitest tests, Playwright journeys, and Axe accessibility checks.

### Dependency installation

An npm dependency installation was attempted with the repository's package configuration using `npm install --ignore-scripts`. The attempt timed out because registry/network access is unavailable in the sandbox, and `frontend/node_modules` remained absent.

### TypeScript

A global TypeScript compiler is present, but the frontend dependency tree is not installed.

Command:

```text
npm run typecheck
```

Result: **BLOCKED / exit 2**.

Exact blocker:

```text
error TS2688: Cannot find type definition file for 'vite/client'.
```

### Lint / build / unit tests

The following commands were attempted:

```text
npm run lint
npm run build
npm test
```

Results: **BLOCKED / exit 127** because `eslint`, `vite`, and `vitest` are not installed in `node_modules`.

### E2E / accessibility

Commands:

```text
npm run test:e2e
npm run test:a11y
```

Result: **BLOCKED** because Playwright is not installed locally; the available global command does not provide the project's Playwright test runner.

The repository contains seven browser journeys plus an Axe accessibility suite, with mutation-oriented E2E paths controlled by explicit environment/test flags.

### npm audit

Command:

```text
npm audit --audit-level=high
```

Result: **BLOCKED / exit 1**.

Exact reason: npm requires an existing lockfile for audit, and the repository does not currently contain `package-lock.json`. A clean network-enabled dependency install should generate and commit the lockfile before production use.

## API contract and frontend API boundary

The repository contains **81 FastAPI route handlers** and a generated `API_CONTRACT_MATRIX.md` inventory covering method, path, auth requirement, request/query shape, response annotation, handler, frontend consumer, and status.

Browser HTTP calls are centralized in `frontend/src/api.ts`; a source scan found no `fetch`, Axios, or XMLHttpRequest use scattered across feature components.

Agent run forms are derived from the backend's Pydantic catalog endpoint rather than guessed frontend payloads.

## Authentication and authorization verification

Implemented controls include:

- persisted refresh-token sessions
- refresh-token rotation and revocation
- server-side `/auth/me` identity resolution
- database-authoritative role/permission resolution
- permission-guarded frontend routes
- fail-closed public registration in production
- explicit production boot checks for default JWT and database credentials

A production fail-fast configuration check was executed successfully: leaving the default production JWT secret or default database password causes settings validation to fail rather than allowing startup.

Full authentication/RBAC integration execution remains blocked by the unavailable repository dependencies/PostgreSQL environment.

## Approval safety verification

Implemented controls include:

- approval state separate from execution state
- explicit allowlisted command registry
- server-side permission recheck
- row locking for approval execution
- current entity-state validation
- stable persisted idempotency keys for actionable approvals
- HTTP `Idempotency-Key` contract support
- idempotent payment execution behavior
- separate execution status/error/result fields
- audit records for approval and execution outcomes

The current executable approval command is deliberately limited to `payment_execute`; unsupported recommendations remain reviewable but non-executable until a typed command is explicitly added.

## Audit verification

Implemented controls include:

- durable PostgreSQL `audit_logs`
- database-enforced append-only update/delete protection
- serialized hash-chain state
- correlation IDs
- actor/action/resource/outcome fields
- credential/token metadata redaction
- audit query and chain verification endpoints

A future hardening item remains: an independent failure-event audit sink outside the business transaction is not implemented, so a rolled-back transaction can roll back its same-transaction audit record.

## SAP verification

Status: **BLOCKED_EXTERNAL_SAP**.

Implemented locally:

- backend-only SAP credentials
- Service Layer login/session management
- bounded automatic retries for safe read operations
- no automatic replay for mutating transport ambiguity
- mutation/session-expiry paths that surface reconciliation-required conditions
- document/master-data mappers
- SAP response/error normalization
- local duplicate prevention using persisted SAP identifiers and row locking
- controlled synchronization outcomes
- SAP integration status UI that does not claim live connectivity when it has not been verified

No live SAP Business One tenant, CompanyDB, or controlled credentials were available. Therefore no live posting or live compatibility claim is made.

The current documented SAP state is:

**implemented** → **locally source/unit tested where dependencies permit** → **live verification pending controlled SAP Business One environment**.

## Security

Repository scans found no committed:

- `.env`
- PEM/key/certificate artifact
- private credential file
- database/SAP/LLM secret file

The browser has no SAP/database/LLM credentials.

Security hardening implemented includes centralized server auth, RBAC enforcement, session rotation, CORS correction for bearer-header architecture, security headers, conservative sensitive-endpoint rate limiting, secret redaction in audit metadata, and explicit production configuration validation.

Security tooling could not be executed locally because Bandit, pip-audit, ESLint, and npm dependency data are unavailable in this sandbox.

## Infrastructure

The repository now includes:

- backend Dockerfile
- frontend multi-stage Dockerfile
- Nginx SPA/API proxy configuration
- PostgreSQL service
- Redis service
- Qdrant service
- API/worker services
- health checks
- migration-on-start behavior for the local/staging-like compose stack
- CI for backend, frontend, and browser QA

Docker validation is **BLOCKED** because the Docker executable is not installed in the current environment.

## CI/CD

A GitHub Actions workflow is present for:

1. dependency installation
2. compile/migration checks
3. unit/integration tests
4. Ruff/Black/MyPy
5. Bandit/pip-audit
6. frontend typecheck/lint/tests/build/audit
7. browser E2E
8. Axe accessibility verification

CI test JWT/E2E credentials are generated per run rather than committed as reusable secrets.

## Final production-readiness status

**NOT YET PRODUCTION VERIFIED.**

The repository is materially hardened and production-oriented, but the evidence does not support a full production-ready claim in this environment.

### Remaining blockers before production acceptance

- install the declared backend dependencies and execute the complete unit/integration suite against clean PostgreSQL
- execute Ruff, Black, MyPy, Bandit, and pip-audit
- install frontend dependencies and generate/commit a lockfile
- execute frontend typecheck, lint, Vitest, production build, Playwright, and Axe
- run Docker Compose build/start/health checks
- replace the process-local rate limiter with distributed Redis-backed enforcement before horizontal scaling
- perform controlled live SAP Business One verification using an approved test company/database
- confirm SAP payment/document object mappings against the exact target SAP Business One release
- add MFA/SSO when required by the enterprise identity policy
- consider an independent durable audit sink for failures that occur during rolled-back business transactions


## Current working-tree verification (2026-10-10)

| Check | Current evidence | Result |
|---|---|---|
| Python syntax | `python -m compileall -q app tests alembic` | PASS |
| Focused unit cohort | Aging + AP-priority + SAP mapping/document mapping + currency response schemas + service filtering/pagination | **120 passed, 1 skipped** (SAP API mock test module skipped because `tenacity` is missing) |
| Coverage output | Focused pytest-cov report | Emits **25% aggregate repository coverage** for the current focused selection only; **not** a full-suite coverage result because full pytest cannot collect. |
| Currency correctness | Mixed AR/AP customer/vendor/portfolio regressions, precision/invalid/zero/negative cases and Pydantic response-contract tests | PASS within focused cohort |
| Filter and pagination correctness | Customer minimum-amount/search/pagination and vendor search/pagination service tests | PASS within focused cohort |
| Isolated frontend formatter checks | Transpile the current `formatters.ts` source and call currency grouping/precision cases directly | **5/5 passed**; this is not Vitest or a TypeScript typecheck |
| SAP role boundary regression | `tests/unit/test_security.py` role-map test authored for `agent:configure` | **Not executed here** because security module dependencies are incomplete; full pytest also blocked at `asyncpg` before collection |
| Full pytest | `pytest -q` | BLOCKED: `asyncpg` missing when integration fixtures import |
| Standard frontend typecheck | `npm run typecheck` | BLOCKED: missing `vite/client` types/dependencies |
| Lint/unit/build | `npm run lint`, `npm test -- --run`, `npm run build` | BLOCKED: ESLint, Vitest and Vite not installed |
| Dependency scan | `npm audit --audit-level=high` | BLOCKED: no lockfile; registry unavailable |
| Python security/static scans | Ruff, Black, MyPy, Bandit, pip-audit | BLOCKED: tools not installed |
| DB/migrations/Docker | Online migrations, clean PostgreSQL, Docker Compose | BLOCKED: no configured test DB and Docker CLI missing |
| Browser/accessibility | Playwright/Axe across desktop/tablet/mobile | BLOCKED: test dependencies/browser journey not available |
| SAP read-only endpoint | Code present; mock endpoint tests added | MOCK TEST BLOCKED by missing `tenacity`; live SAP status `BLOCKED_EXTERNAL` |

The project remains **hardened implementation with partial local verification; production acceptance pending**. No browser, Docker, online database, dependency audit or live SAP result is reported as passed.

## Pass 2 verification record (2026-10-14)

The sandbox had Python 3 with PyJWT only, Node 22 with TypeScript, no network, no Docker and no browser. The results below are exactly what ran. Items marked NOT RUN are not claimed as passing.

### What ran

| Check | Command or method | Result |
|---|---|---|
| Python compile | `python -m compileall -q app tests alembic` and `py_compile scripts/create_user.py` | PASS |
| Pure Python unit tests | 31 unit test modules exist. A local stand in for pytest ran the 5 whose imports need nothing beyond the standard library: `test_aging_calculations`, `test_ap_priority_calculations`, `test_report_currency`, `test_client_ip`, `test_approval_views`. | **125 tests passed in those 5 modules.** The other 26 modules import FastAPI, Pydantic, SQLAlchemy, passlib or tenacity, which are not installed here, so they were not executed. That includes the pass 1 SAP endpoint tests and the pass 1 schema tests, which therefore remain unexecuted. |
| New Python tests that ran | `test_report_currency` (13), `test_client_ip` (13), `test_approval_views` (7) | 33 passed, included in the 125 |
| Frontend logic tests | `api`, `auth`, `router`, `csv`, `formatters` test files, transpiled with TypeScript and run by a small local runner that mimics the Vitest functions used | **42 passed.** A deliberate break of the refresh sharing and replay safety code on a copy made 6 of them fail, so they do detect regressions. |
| TypeScript strict check | `tsc` 6.0.3 with the project `tsconfig.json` plus local stand in declarations for React, because `@types/react` could not be installed. `--noUnusedLocals --noUnusedParameters` also on. | 0 errors. This is a smoke check, not the real `npm run typecheck`: JSX attribute types are not checked and the real React types may report additional problems. |
| Import and export consistency | script over every relative import in `frontend/src` | 0 problems |
| YAML and JSON validity | `ci.yml`, `docker-compose.yml`, `package.json`, `vercel.json` | PASS |

### What did not run

| Check | Why |
|---|---|
| `pytest` on PostgreSQL, integration tests (including the new mixed currency report test) | no PostgreSQL, dependencies not installable |
| Black, Ruff, MyPy, Bandit, pip-audit | tools unavailable. New Python was written to Black's style but never formatted by it. |
| `npm ci`, ESLint, Vitest component tests, `vite build`, `npm audit` | no registry access. There is still no `package-lock.json`. |
| Playwright (mocked, real backend, axe, viewport overflow) | no browser |
| Docker build and compose start, migration on a real database | no Docker. No migration was added in this pass. |
| Live SAP verification | BLOCKED_EXTERNAL, no approved test company |
| CSP validation in a browser | no browser |

### Defects found and fixed in this pass

See `REMEDIATION_CHANGELOG.md` (pass 2). The most important: General Ledger reports summed currencies; the rate limiter could be bypassed with a forged header; approved requests could not be found after a reload; there was no way to create a production user.

### Verdict

Suitable for a controlled go live on a single API instance after the gates in `docs/GO_LIVE_CHECKLIST.md` section A are completed and pass. It is not verified production ready today because the checks above that need real dependencies have not been run by anyone.

## Pass 3 verification record (2026-10-18) — supersedes the pass 2 figures above

This pass followed the first run on a real developer machine (Windows, PostgreSQL, Python 3.12). That run found three defects no offline check had caught: the `.env` file was ignored, migration 0012 could not run on PostgreSQL, and CORS sat in the wrong middleware position. All three are fixed (see `REMEDIATION_CHANGELOG.md`). It is the clearest evidence that offline checks are not a substitute for running the project, so the verification below is split into what ran here and what only your machine can run.

### Ran in the offline sandbox (no network, no Docker, no PostgreSQL, no browser)

| Check | Result |
|---|---|
| Python compile of `app`, `tests`, `alembic`, `scripts` | PASS |
| Python tests that can import without the web stack | **134 passed**, 0 failed, in 7 of the 34 unit modules: aging and AP calculations, report currency, client address and rate limit scope, approval views, migration revision guard, local helper script |
| Internal import resolution (every `from app...` in app, tests, scripts, alembic) | 845 imports checked, 0 unresolved |
| Undefined name scan (a pyflakes style check over 265 Python files) | 0 problems |
| ORM models against migrations (every mapped column exists in a migration) | 0 missing columns |
| Frontend logic tests (API client, router, CSV, formatters, auth, chart data, quick search) | **58 passed**, 0 failed, 7 files. A deliberate break of the refresh and replay code made tests fail, so they detect regressions. |
| TypeScript strict check, `noUnusedLocals`, `noUnusedParameters` | 0 errors, using local stand in React types |
| Frontend import and export consistency, icon names, CSS class names | 0 problems |
| YAML and JSON validity (CI, compose, package, vercel) | PASS |

### Cannot run here. Run `python scripts/dev.py check --fix --e2e` on your machine

| Check | Why it matters |
|---|---|
| The other 27 Python unit modules (they import FastAPI, Pydantic, SQLAlchemy, passlib or tenacity) | including the new `.env` tests |
| 16 PostgreSQL integration modules, including the new mixed currency report test | the migrations now reach head only if every step after 0012 also succeeds. 0013 and 0014 have not been executed by anyone. |
| Black, Ruff, MyPy, Bandit, pip-audit | New Python was written to the project style but never formatted by the tools; expect `--fix` to change some lines |
| `npm run typecheck` with real React types, ESLint, Vitest component tests, `vite build`, `npm audit` | `npm install` reported 14 vulnerabilities (2 critical, 11 high) on your machine. They are not triaged. Do not run `npm audit fix --force`. |
| Playwright journeys and axe accessibility | 4 spec files, none executed |
| Content Security Policy in a real browser | the nginx policy is untested |
| SAP | no tenant. Nothing about SAP is verified. |

### Honest status

Not "error free". It is an internal build that has been run once on a real machine and corrected, with a single command (`scripts/dev.py check`) that reports every remaining failure in one table. Expect the first `check --fix` to surface a small number of lint, type or formatting issues. Send `verify-report.txt` and they get fixed from evidence.
