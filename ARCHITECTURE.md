# Architecture

## Product boundary

Vertex Data Systems Finance AI Platform is a FastAPI-based finance operations backend with a React/Vite frontend. The backend owns finance calculations, approval state, authorization, persistence, audit records, SAP integration, and agent execution. The browser consumes only backend contracts.

## Request flow

Browser → React API client → FastAPI middleware → authenticated/authorized route → service → repository → PostgreSQL.

External calls occur only from backend integration layers:

- SAP Business One Service Layer
- LLM providers
- Redis/Celery/Qdrant where configured

## Backend boundaries

`app/api/v1/` contains transport-level route handlers and permission dependencies.

`app/services/` contains finance and application use cases.

`app/repositories/` owns SQLAlchemy data access and row-locking queries for financial mutations.

`app/agents/` contains deterministic finance/AI decision agents. Agent output is validated by Pydantic schemas. LLM output is treated as untrusted input.

`app/integrations/sap/` isolates SAP Service Layer authentication, request handling, error normalization, and mapping.

`app/db/models/` is the durable data model. Alembic migrations are the schema delivery mechanism.

## Authorization model

JWT access tokens identify the subject, but the backend rereads the active user from PostgreSQL for protected requests and derives permissions from the persisted role. Token claims are not treated as the current authorization source.

## Approval model

AI recommendation → persisted approval request → human approval/rejection → separate typed execution command.

Execution uses an allowlisted action registry. Free-form service or method names from frontend/LLM payloads are never executed.

## Audit model

`audit_logs` is append-only at the database boundary and linked into a hash chain via `audit_chain_state`. Audit metadata is recursively sanitized before storage. Successful business actions and their audit entries share a transaction. This preserves consistency but also means an application transaction rollback can roll back its same-transaction audit event; a separate independent failure-event sink is not yet implemented.

## Financial truth

Financial calculations remain in backend services. React only formats and renders backend results. No frontend code computes tax, aging, P&L, balance sheet, risk scores, payment totals, or SAP synchronization outcomes.

## Deployment

The repository now includes:

- backend application image
- frontend Nginx image with SPA fallback and `/api/` proxy
- PostgreSQL
- Redis
- Qdrant
- Celery worker

Live SAP and LLM connectivity remain environment-dependent and are never faked.


## Currency-safe AR/AP summaries (2026-10-10)

AR aging/customer and AP/vendor/portfolio aggregators group open monetary values by each document's currency. They do not convert currencies. If more than one currency is in scope, scalar amount fields are null; clients must consume `currency_balances`. Unknown/missing codes stay explicit (`UNSUPPORTED:<code>` / `UNSPECIFIED`) rather than being labelled PKR. Customer credit limits apply only to documents matching the configured customer default currency.

## SAP verification boundary

`GET /api/v1/sap/status` reports configuration only and keeps `live_connection_verified=false`. `POST /api/v1/sap/verify` performs a bounded, read-only Service Layer `BusinessPartners` query with TLS certificate verification and server-side credentials, returning a safe state and correlation ID. Interactive sync is limited to vendor/customer master data and requires `agent:configure`; financial document and payment writes are not invocable through the current SAP agent route until an approval-bound execution/reconciliation workflow exists.
