# Frontend QA Matrix

Status date: **2026-10-09**

The React application uses Vite, a centralized API client, shared formatting helpers, route permission guards, loading/empty/error states, and an enterprise visual system. Automated frontend tests could not be executed in this environment because frontend dependencies were not installed and network access to the npm registry was unavailable.

| Page | Render | API | Loading | Empty | Error | Permission | Responsive | Accessibility | E2E |
|---|---|---|---|---|---|---|---|---|---|
| Login | IMPLEMENTED | auth | YES | N/A | YES | N/A | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |
| Dashboard | IMPLEMENTED | aging, AP, approvals | YES | YES | YES | YES | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |
| Receivables | IMPLEMENTED | aging | YES | YES | YES | YES | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |
| Customer Detail | IMPLEMENTED | aging, collections agent | YES | YES | YES | YES | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |
| Payables | IMPLEMENTED | AP priority | YES | YES | YES | YES | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |
| Approval Inbox | IMPLEMENTED | approvals | YES | YES | YES | YES | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |
| AI Agent Center | IMPLEMENTED | agent catalog + run | YES | YES | YES | YES | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |
| Reports | IMPLEMENTED | trial balance, P&L, balance sheet | YES | YES | YES | YES | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |
| SAP Integration | IMPLEMENTED | SAP status + read-only verify + master-data agent (configure permission) | YES | YES | YES | YES | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |
| Audit Center | IMPLEMENTED | audit logs + verification | YES | YES | YES | YES | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |
| Settings | IMPLEMENTED | session/user context | YES | N/A | YES | AUTHENTICATED | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |
| Vendor Detail | IMPLEMENTED | AP-priority exposure, filtered obligations, permission-scoped vendor profile | YES | YES | YES | invoice:read plus vendor:read for profile | IMPLEMENTED_NOT_BROWSER_VERIFIED | TEST_DEFINED_NOT_RUN | BLOCKED_ENVIRONMENT |

E2E journeys are environment-driven to avoid creating or mutating finance data in an uncontrolled environment. Mutation tests require explicit flags and test identifiers.


## Current remediation update (2026-10-10)

Dashboard, Receivables, Customer Detail, Payables, and Vendor Detail now render the backend's per-currency balances and do not label mixed-currency totals PKR. The SAP UI invokes `POST /sap/verify` via the central backend API client and hides sync controls unless `agent:configure` is granted; the server is authoritative. Real `tsc`, lint, Vitest, Vite build, Playwright and Axe remain blocked by missing frontend dependencies; responsive/accessibility tests were not observed in a real browser.

## Pass 2 update (2026-10-14)

Routes are real URLs. "Real URL" means the page can be reloaded, bookmarked and used with the back button. NOT RUN means defined but not executed in this environment.

| Workspace | URL | Permission | Data source | States | Changes in pass 2 |
|---|---|---|---|---|---|
| Sign in | `/` when signed out | none | `POST /auth/login`, `GET /auth/me` | error, rate limited, session expired notice | show password toggle, retry delay shown |
| Overview | `/` | per panel | aging, AP summary, approval summary and list | independent panels, each with retry | no mixed currency totals |
| Receivables | `/receivables` | `ar_invoice:read` | aging summary, customers, invoices | loading, empty, error, pagination per list | pagination fixed |
| Customer | `/receivables/customers/:id` | `ar_invoice:read` | existing page | unchanged logic | now a real URL |
| Payables | `/payables` | `invoice:read` | AP priority | unchanged logic | links to vendor URL |
| Vendor | `/payables/vendors/:id` | `invoice:read` | existing page | unchanged logic | now a real URL |
| Approval inbox | `/approvals` | `approval_request:read`; actions need `approval_request:action`, execute also `payment:approve` | `/approval-requests` views and summary | six lifecycle tabs | approved and failed items stay reachable |
| AI Agents | `/agents` | `agent:invoke` | unchanged | unchanged | none |
| Reports | `/reports` | `report:view` | currencies, three reports | currency required when several | single currency reports, CSV |
| SAP | `/sap` | `agent:invoke`; sync needs `agent:configure` | status, verify, agent run | evidence ladder | confirmation before writes |
| Audit Center | `/audit` | `audit_log:read` | logs with filters, verify | empty, error, pagination | contract mismatch fixed |
| Settings | `/settings` | signed in | readiness, SAP status | live | no static claims |
| Not found | any other path | none | none | explicit page | no silent dashboard fallback |

Automated coverage that exists:

- Logic tests in `src/*.test.ts` (API client, router, CSV, formatters, auth): 42 passed in an offline runner. The same files are written for Vitest and should be run with `npm test` (NOT RUN here).
- `Login.test.tsx` component tests: NOT RUN.
- `e2e/mocked.spec.ts` (fake backend): covers not found, permission denied, deep link reload, session expiry, double click on execute sending one request, dialog focus, currency choice, mobile drawer and server confirmed identity. NOT RUN.
- `e2e/accessibility.spec.ts`: axe at 1280 and 390 pixel widths plus a horizontal overflow check at 360. NOT RUN.
- `e2e/app.spec.ts`: seven journeys against a real backend, mutations opt in. NOT RUN.

No claim of responsive or accessibility compliance is made until those browser tests run.
