# API QA Matrix

Status date: **2026-10-09**

The historical inventory contained **81** FastAPI route handlers; current source has **82** after adding `POST /sap/verify`. The source inventory is in `API_CONTRACT_MATRIX.md`. Contract and domain unit tests exist across the repository, but the complete suite could not be collected because two installed dependencies are missing from the execution environment (`passlib` and `tenacity`).

| Scope | Auth | RBAC | Validation | Error handling | DB integration | Frontend | E2E | Status |
|---|---|---|---|---|---|---|---|---|
| Authentication | TESTED IN CODE | TESTED IN CODE | Pydantic | structured | integration tests present | API client | defined | BLOCKED_ENVIRONMENT |
| Vendor/customer CRUD | TESTED IN CODE | permission dependencies | Pydantic | structured | integration tests present | backend-first | defined | BLOCKED_ENVIRONMENT |
| Invoices/payments | TESTED IN CODE | permission dependencies | Pydantic | structured | integration tests present | backend-first | defined | BLOCKED_ENVIRONMENT |
| Aging/AP priority | TESTED | permission dependencies | Pydantic | structured | unit/integration | yes | defined | BLOCKED_ENVIRONMENT |
| Approvals | TESTED IN CODE | permission + action registry | Pydantic + server checks | structured | integration tests present | yes | defined | BLOCKED_ENVIRONMENT |
| Agents | TESTED | agent permission | catalog-generated schemas | structured | integration tests present | yes | defined | BLOCKED_ENVIRONMENT |
| Reports | TESTED IN CODE | report:view | Pydantic | structured | integration tests present | yes | defined | BLOCKED_ENVIRONMENT |
| SAP | read-only verification endpoint; mocked tests skipped here | `agent:invoke` for read, `agent:configure` for master-data sync | Pydantic + mapper validation | normalized SAP errors | integration paths present | yes | controlled | BLOCKED_EXTERNAL_SAP |
| Audit | implementation complete | audit_log:read | query bounds | structured | durable DB chain | yes | defined | BLOCKED_ENVIRONMENT |
| Health | implementation complete | public operational probe | none | dependency failure via 5xx | DB readiness | shell checks | defined | BLOCKED_ENVIRONMENT |
| Vendor response data privacy | Role-derived | vendor:bank_details:read | Pydantic response masking | structured | unit regression added, not runnable here | Vendor Detail | defined | BLOCKED_ENVIRONMENT |
| 401 refresh of financial mutations | Authenticated | original command permission | request method + Idempotency-Key check | normalized API error | frontend unit tests added, not runnable here | centralized API client | defined | BLOCKED_ENVIRONMENT |


## Current remediation update (2026-10-10)

The current source has 82 route decorators after adding `POST /sap/verify`. AR/AP aggregate contracts now expose `currency_balances`; mixed-currency scalar amounts serialize as null. Added pure regression tests, Pydantic response-contract tests, and customer/vendor filter/pagination tests passed. The latest focused cohort including filter/pagination regressions reports 120 passed and 1 skipped (the SAP API mock test module is skipped because the declared `tenacity` dependency is missing). Full pytest is blocked by missing `asyncpg`; SAP live verification remains external and unperformed. The SAP synchronization route now requires `agent:configure` and accepts only `vendor`/`customer` entity types; financial documents and payments are not interactive-sync options.

- Interactive SAP synchronization now requires `agent:configure` rather than general `agent:invoke`, and the typed request accepts only `vendor` / `customer`; the API catalog omits that agent for lower-privilege roles. The read-only `/sap/verify` probe retains `agent:invoke`.
