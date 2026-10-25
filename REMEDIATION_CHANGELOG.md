# Remediation Change Log

Review date: 2026-10-10. The supplied ZIP had no Git metadata; this is a file-based change log, not a Git diff or commit history.

## Financial correctness and API contracts

| File | Problem addressed | Change and evidence |
|---|---|---|
| `app/services/currency_utils.py` (new) | Currency was treated as a display attribute rather than the unit of the amount. | Normalizes the six currency codes supported by the existing domain contract; missing/unknown codes become explicit `UNSPECIFIED` / `UNSUPPORTED:<code>` groups. Performs no FX conversion. |
| `app/services/aging_calculations.py` | AR customer/portfolio totals added different invoice currencies. | Introduces per-currency customer and portfolio balances; scalar monetary totals are null for mixed-currency records; credit limit is applied only to customer default-currency exposure. |
| `app/services/aging_service.py` | Filters assumed every summary has one scalar amount. | Keeps mixed-currency customers when a currency-specific balance meets the filter. |
| `app/services/ap_priority_calculations.py` | AP portfolio/vendor exposure/status amounts could mix currencies. | Groups vendor exposure, totals, status amounts, overdue amounts, and recent executed activity by document currency using `Decimal`. |
| `app/services/ap_priority_service.py` | Service-level AP summary returned blended nominal sums. | Delegates to the currency-grouped calculation function. |
| `app/schemas/aging.py`, `app/schemas/ap_priority.py`, `app/api/v1/aging.py` | API response contracts could not express currency groups/ambiguous totals. | Added typed breakdown schemas and nullability for misleading flat totals; per-currency aging percentages are returned. |
| `app/agents/collections/agent.py` | Collection financial impacts could be generated from a blended customer sum. | Splits collection assessments by currency before emitting financial impacts; unsupported currency impacts fail safely. |
| `tests/unit/test_aging_calculations.py`, `tests/unit/test_ap_priority_calculations.py`, `tests/unit/test_currency_response_schemas.py`, `tests/unit/test_currency_service_filters.py` (new) | No regression coverage for mixed-currency and serialization behavior. | Added mixed-currency, huge Decimal, zero/negative exposure, currency validation, default-currency credit limit, Pydantic response-contract, minimum-amount filtering, search, sorting and pagination tests. |

## SAP integration boundary and security

| File | Problem addressed | Change and evidence |
|---|---|---|
| `app/schemas/sap_status.py` | The module duplicated router source and did not define the imported status response model. | Replaced with explicit secret-free status/verification contracts. |
| `app/api/v1/sap.py` | Configured URL could be mistaken for live connection proof; no reliable read-only probe contract existed. | Adds `POST /sap/verify`, which performs a bounded, read-only BusinessPartners query, enforces TLS verification, returns safe status/error states and a correlation ID, and never returns credentials. |
| `app/core/config.py`, `.env.example` | TLS verification needed a hard fail-safe for enabled SAP. | Fails settings validation if SAP is enabled with TLS verification off; documents `SAP_VERIFY_SSL=true`. |
| `app/schemas/agent.py`, `app/agents/sap_integration/agent.py`, `app/api/v1/agents.py` | Interactive SAP agent accepted payment/accounting-document writes under general agent invocation permission. | Restricts the interactive entity schema/executor to customer/vendor master data, requires `agent:configure`, and hides the agent from catalogs for users lacking that permission. Financial-document/payment sync service code remains in the repository but is not invocable through this endpoint. |
| `frontend/src/App.tsx`, `frontend/src/pages/SapIntegration.jsx` | UI lacked honest read-only live-status verification and client-side permission presentation. | Connects the new verification endpoint through the central API client; shows backend state, checked time and correlation ID; only presents sync controls to configure-role users. Backend remains authoritative. |
| `tests/unit/test_sap_api.py`, `tests/unit/test_security.py` (new/extended) | No endpoint test cases for normalized SAP probe outcomes or a direct role grant regression. | Adds mocked configuration, TLS, auth, transport, successful read, and rejected-read tests, plus a role-permission regression for `agent:configure`. The endpoint module is currently skipped due missing `tenacity`; the security test module is blocked in this environment by missing `passlib`/full-suite collection. These are not counted as passes. |

## Frontend and documentation

| File(s) | Problem addressed | Change and evidence |
|---|---|---|
| `frontend/src/formatters.ts`, `frontend/src/formatters.test.ts` | Frontend could show mixed-currency amounts under one hardcoded/default currency. | Adds display-only currency breakdown formatting with no monetary arithmetic; adds formatter regressions. |
| `frontend/src/pages/Dashboard.jsx`, `Receivables.jsx`, `CustomerDetail.jsx`, `Payables.jsx`, `VendorDetail.tsx`, `frontend/src/styles.css` | AR/AP summary displays assumed scalar totals or PKR formatting. | Renders explicit backend currency balances in summary cards/tables/detail views and styles currency group boundaries. |
| `README.md`, `ARCHITECTURE.md`, `API_CONTRACT_MATRIX.md`, `API_QA_MATRIX.md`, `FRONTEND_QA_MATRIX.md`, `FINAL_TECHNICAL_AUDIT.md`, `FINAL_QA_REPORT.md`, `REMAINING_WORK_AND_ACCEPTANCE.md`, `PROJECT_STATUS_AND_ROADMAP.md`, `SECURITY_REVIEW.md`, `SAP_INTEGRATION.md`, `SAP_LIVE_VERIFICATION.md` | Earlier reports described the initial defects and counts but not the current remediations. | Added current status and actual results, updated SAP endpoint/permission scope, and preserved external blockers rather than claiming completion. |

## Verification snapshot

- `python -m compileall -q app tests alembic`: PASS.
- Focused calculations/mapping/response-schema plus service filter/pagination tests: **120 passed, 1 skipped**. The SAP route and role-permission tests are also authored, but could not execute here due missing declared dependencies. SAP endpoint tests are skipped because `tenacity` is not installed in this environment.
- Alembic: one head, `0014_approval_idempotency_key`; offline SQL generation passed (775 lines). No online DB migration was run.
- Frontend syntax-only parse: 29 JS/TS/JSX/TSX files, zero parse diagnostics. Isolated formatter checks against the transpiled current source pass **5/5**. Neither result is a real typecheck/build or Vitest suite.
- Full `pytest`: blocked before collection by missing `asyncpg`. Typecheck is blocked by missing `vite/client`, ESLint/Vitest/Vite are not installed, npm audit and lockfile generation are blocked by unavailable registry/cache, Python static/security tools and Docker are unavailable.
- No PostgreSQL, Docker, browser/Axe, or live SAP test was performed. Production acceptance remains pending.

# Remediation Change Log, pass 2 (2026-10-14)

File based log again: the archive has no Git metadata. "Verified" below names the exact check that ran in the offline sandbox. Anything marked NOT RUN needs the gates in `docs/GO_LIVE_CHECKLIST.md`.

## Financial correctness

| File | Problem | Change | Verification |
|---|---|---|---|
| `app/services/financial_reporting_service.py`, `app/services/report_currency.py` (new), `app/schemas/financial_report.py`, `app/api/v1/reports.py` | Trial balance, profit and loss and balance sheet summed journal lines across every currency, the same defect as the AR and AP one, missed in pass 1. The UI then labelled the result PKR. | Reports are produced for one currency. `currency` query parameter, `currency` and `available_currencies` on every report, new `GET /reports/currencies`. Without `currency`, one posted currency is chosen automatically and several are refused with 422 listing the choices. No exchange rate is applied. | `tests/unit/test_report_currency.py` 13 passed. Integration tests updated to pass `currency=USD` and a new `test_reports_never_combine_currencies` added: NOT RUN (needs PostgreSQL). |

## Security and correctness of server behaviour

| File | Problem | Change | Verification |
|---|---|---|---|
| `app/core/middleware.py`, `app/core/client_ip.py` (new), `app/core/config.py` | The rate limiter keyed on the client supplied `X-API-Key` header, so rotating it gave unlimited login attempts. Behind nginx every user shared one address. Limits were scoped per concrete URL so each UUID got a fresh allowance. The docstring claimed Redis. | Key on the network address with an explicit `APP_TRUSTED_PROXY_HOPS`; scope limits per route shape; docstring now states the limiter is in process. JWT secret must be 32 or more characters in staging and production. | `tests/unit/test_client_ip.py` 13 passed |
| `app/services/approval_views.py` (new), `app/repositories/approval_request_repository.py`, `app/services/approval_service.py`, `app/api/v1/approval_requests.py`, `app/schemas/approval_request.py` | The inbox listed only `pending`. After approval a request vanished, so an approved action awaiting execution, or one whose execution failed, could not be found, executed or reconciled after a reload. The badge counted at most 100. | `GET /approval-requests?view=` (default `pending`, unchanged) with `awaiting_execution`, `executing`, `failed`, `executed`, `rejected`, `approved`, `all`; `GET /approval-requests/summary` with exact counts. | `tests/unit/test_approval_views.py` 7 passed. Endpoint behaviour NOT RUN. |
| `app/services/approval_service.py` | A failed execution stored `str(exc)` on the record, which the API returns. That can expose SQL or host names. | Business errors keep their message; anything else becomes a generic message. Full detail goes to the server log. | `test_approval_views.py` covers the sanitiser. |
| `app/main.py` | Validation errors had a different shape from other errors and no correlation id. The browser could not read `X-Correlation-ID` across origins. | 422 and 500 bodies carry `correlation_id` and the standard error fields (`detail` kept for compatibility). CORS exposes `X-Correlation-ID` and `Retry-After`. | compile only |
| `scripts/create_user.py` (new), `Dockerfile` | In production registration is off and no other way existed to create a user. | Operator command that reuses `AuthService.register`, prompts for the password and never accepts it on the command line. | compile only. NOT RUN against a database. |

## Frontend

| Area | Change | Verification |
|---|---|---|
| `src/api.ts` | One shared token refresh for concurrent 401s (previously each request refreshed, which logs the user out under refresh token rotation). Transient refresh failures no longer end the session. Request cancellation. A mutation that times out says its outcome is unknown. 422 detail arrays, `Retry-After` and correlation ids are surfaced. A refused refresh signs the app out with an explanation. | 42 logic tests passed in an offline runner, and a mutation of the refresh sharing code was caught by them. |
| `src/router.ts`, `src/navigation.ts`, `src/App.tsx` | Real URLs including `/receivables/customers/:id` and `/payables/vendors/:id` (previously session storage, so no reload, bookmark or back button). Unknown URLs show a not found page, not the dashboard. Lazy loaded workspaces, error boundary, skip link, focus moves to the page on navigation, idle sign out. | router tests passed; the tests caught and I fixed a trailing slash redirect bug |
| `src/components/ui.tsx` and friends | Typed UI kit. Native `<dialog>` confirmation (replaces `window.confirm`). Keyboard operable tabs. Focusable table scroll regions. Shield icon was missing and fell back to a file icon. | strict type smoke check clean (see FINAL_QA_REPORT) |
| `Receivables` | Customer pagination buttons did nothing and invoice paging always requested page 1. | rewritten with one page state per list |
| `Reports` | Every amount defaulted to PKR. | currency selector, labelled amounts, CSV download (formula injection safe) |
| `Audit` | Read `last_sequence`, which the API does not return ("through sequence undefined"), sent `limit` instead of `page_size`, showed dates without times, no filters. | matches the real contract, filters, pagination, on demand verification |
| `Approvals` | Approved requests disappeared from the inbox after approval (backend listed only `pending`); browser `confirm()` for money moving actions. | lifecycle tabs, accessible dialogs, `Idempotency-Key` sent on execute (the value stored on the record, which the server sets when an executable approval is created) |
| `Settings` | A static list claimed features were "built". | live readiness and honest known limits |
| `SapIntegration` | Showed a single banner. | evidence ladder where each step shows only what the server reported; confirmation before any write |
| `Dashboard` | Sequential requests; one failure blanked everything. | independent panels with their own retry |
| `nginx/default.conf`, `Dockerfile`, `vercel.json`, `index.html` | No CSP, no caching rules, root container, no lockfile use. | CSP and headers, unprivileged nginx on 8080, `npm ci` when a lockfile exists. NOT RUN in a browser. |
| `eslint.config.js` | JSX files could not be parsed and browser globals were undefined, so `npm run lint` would have failed. | parser and globals configured. NOT RUN. |
| `e2e/*.spec.ts` | Old journeys targeted buttons and text that no longer matched the UI. | rewritten; `mocked.spec.ts` needs no backend. NOT RUN. |

## Infrastructure and docs

`docker-compose.yml` binds PostgreSQL, Redis, Qdrant and the raw API port to 127.0.0.1, adds restart policies and configurable CORS. `.github/workflows/ci.yml` uses `npm ci` when locked, points the e2e frontend at the API, and builds both Docker images. New `docs/GO_LIVE_CHECKLIST.md`.

## Addendum (2026-10-18): found when first run on a developer machine

| File | Problem | Change | Verification |
|---|---|---|---|
| `app/core/config.py`, `tests/unit/test_config_dotenv.py` (new) | Each settings group (database, security, SAP, and so on) is its own `BaseSettings` and did not inherit the root class's `env_file`, so a local `.env` was silently ignored. Real environment variables (Docker, CI) worked, which hid the defect. Once read, blank lines from `.env.example` such as `SAP_SERVICE_LAYER_URL=` would have failed URL validation. | One shared `_group_config()` gives every group the repository root `.env` (resolved from the file location, not the working directory) and `env_ignore_empty=True`. Real environment variables still win. | compile only here. The new tests need pydantic and run in CI or locally. |
| `alembic/versions/0012_audit_approval_execution.py` (renamed from `0012_audit_and_approval_execution.py`), `alembic/versions/0013_user_sessions.py`, `tests/unit/test_migration_revisions.py` (new) | The revision id `0012_audit_and_approval_execution` is 33 characters. Alembic creates `alembic_version.version_num` as VARCHAR(32), so on PostgreSQL `alembic upgrade head` failed at step 0012 ("value too long for type character varying(32)") and a clean database could never reach head. Nobody had run the migrations on a real PostgreSQL before. | Revision id shortened to 29 characters; 0013 points at the new id. A guard test checks every id is 32 characters or fewer, file names match ids, and the history is one linear chain with one head. | guard test 3 passed. The full upgrade is NOT RUN here (needs PostgreSQL); the first developer run reached 0011 and then hit this error. |
| `app/main.py` | CORS was the innermost middleware. Responses produced by outer layers (429 from the rate limiter) carried no CORS headers, so a browser on another origin (Vite on :3000 calling :8000) treated them as a network failure, and the UI showed "could not be reached" instead of "too many attempts". Browser preflight (OPTIONS) requests also counted against the login limit. | CORS is registered last so it is the outermost application middleware. It now answers preflights itself and adds its headers to every response from the layers it wraps. Unhandled 500s still bypass it (Starlette limitation); the same origin proxy used in Docker is unaffected. | compile only |
| `frontend/src/pages/Login.tsx`, `Login.test.tsx` | When the API could not be reached, sign in showed "the outcome is unknown", wording meant for payments. | Plain message: the sign in service could not be reached. | type smoke check clean; test written, not run |

## Pass 3 (2026-10-18): stricter verification and a more useful frontend

| Area | Change | Verification |
|---|---|---|
| `app/repositories/approval_request_repository.py` | `_view_conditions` returned a bare `list`, which the strict MyPy settings reject. Now `list[ColumnElement[bool]]`. | compile |
| `frontend/vite.config.js` | In development the browser called the API on another origin, so CORS and a frontend `.env.local` were needed and any mismatch looked like "API could not be reached". The dev and preview servers now proxy `/api` to the backend (`VITE_DEV_API_TARGET`, default `http://127.0.0.1:8000`). | config only |
| `frontend/src/pages/Payables`, `CustomerDetail`, `Agents` | Last untyped `.jsx` pages converted to TSX with typed contracts (also removes lint noise: ESLint without the React plugin reports JSX used imports as unused). Behaviour preserved; the Payables "executed" filter now also sends `include_executed=true`, which the API requires, otherwise that filter always returned nothing. Agent Center no longer crashes when a role has an empty catalog. | strict type smoke check; endpoints, parameters and enum values compared against the backend routes and schemas |
| `frontend/src/pages/Dashboard.tsx`, `components/charts.tsx`, `chartData.ts` | Overview shows an attention strip (failed executions, pending decisions, awaiting execution, overdue items; shown only from counts the API returned, and says so when a source failed), stacked aging bars per currency, and an approval pipeline bar. Bar widths use BigInt on the API decimal strings, never floating point, and every segment is named, valued and given a percentage so colour is never the only signal. | 10 chart logic tests |
| `frontend/src/components/CommandPalette.tsx`, `commands.ts` | Ctrl or Cmd + K quick search: jump to any workspace the role may open, or find real customers and vendors by name through the existing search endpoints. | 6 logic tests; component NOT RUN |
| `components/ui.tsx`, `ui.css`, `Login.tsx` | Skeleton loaders instead of spinners, hover and entrance motion (disabled under reduced motion), truthful sign in points. | type smoke check |
| `scripts/dev.py`, `tests/unit/test_dev_script.py` | One command `setup`, `check`, `run` and `user` for Windows, macOS and Linux. `check` runs every step, writes `verify-report.txt` and prints one pass or fail table. | 6 tests passed |
| `README.md`, `docs/GO_LIVE_CHECKLIST.md`, `FINAL_QA_REPORT.md` | Quick start and an honest, itemised verification record. | review |

Correction: the pass 2 note that the old Approvals page sent the `Idempotency-Key` only sometimes was wrong. The server sets a key whenever an executable approval is created, so the old page sent one. The entry above was corrected.
