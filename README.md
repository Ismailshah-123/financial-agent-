# Vertex Data Systems — Finance AI Platform

Enterprise finance operations platform with a FastAPI backend, PostgreSQL persistence, human-in-the-loop AI decisions, a typed approval execution boundary, and a React/Vite control center designed for eventual SAP Business One integration.

## Product principle

The browser is an operations console. The backend is the financial authority.

React never recalculates finance truth. Decimal amounts are formatted without binary floating-point conversion; missing/invalid financial values display as unavailable instead of silently becoming zero. Vendor bank coordinates require a dedicated backend permission, and non-idempotent mutations are not automatically replayed after token refresh without an idempotency key. AI recommends and explains. Human approval is separate from execution. SAP credentials remain server-side.

## Repository

```text
app/                  FastAPI backend, finance services, agents, repositories
alembic/              PostgreSQL schema migrations
frontend/             React/Vite application
scripts/              local setup helpers
tests/unit/           unit and contract tests
tests/integration/    PostgreSQL-backed API workflows
```

## Core capabilities

Accounts receivable, aging, collections, accounts payable, payment prioritization, vendor/customer workflows and detail pages, invoices, credit memos, reconciliation, tax, budgets, period close, reporting, fraud/compliance agents, approval inbox, durable audit trail, and SAP Service Layer integration foundations.

## Quick start (Windows, macOS, Linux)

You need Python 3.12, Node.js 20 or newer and a running PostgreSQL 14 or newer (a local install, or `docker compose up -d postgres`).

```bash
python scripts/dev.py setup        # .venv, dependencies, .env, databases, migrations, npm install
python scripts/dev.py user --email you@company.com --full-name "Your Name" --role finance_director
python scripts/dev.py run          # API on :8000, web app on :3000
python scripts/dev.py check --fix  # every check in one table; writes verify-report.txt
```

On Windows use `py -3.12 scripts\dev.py ...` if `python` is not on your PATH. In development the web app proxies `/api` to the backend, so no CORS setup or frontend `.env` file is needed. The manual steps below do the same thing one command at a time.

## Local backend setup

Copy `.env.example` to `.env` and set a strong `SECURITY_JWT_SECRET_KEY` for any shared environment.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Frontend setup

```bash
cd frontend
npm run lockfile   # first time only: writes package-lock.json. Commit it.
npm ci
npm run dev
npm run check      # typecheck, lint, tests and production build
```

The app uses real URLs (for example `/receivables/customers/<id>`), so a production web server must fall back to `index.html` for unknown paths. The bundled nginx and `vercel.json` already do.

In development `/api` is proxied to `http://127.0.0.1:8000` (override with `VITE_DEV_API_TARGET`). Set `VITE_API_BASE_URL` only to call a different API origin directly. Do not put SAP, database, LLM, JWT, or other private credentials in Vite variables.

## Docker Compose

The repository includes application images plus PostgreSQL and Redis infrastructure.

```bash
cp .env.example .env
docker compose up --build
```

Only the web app (port 3000) is published to the network. The API (8000), PostgreSQL, Redis and Qdrant are bound to 127.0.0.1 for local development. The API container runs `alembic upgrade head` before starting FastAPI. The frontend image uses Nginx to serve the SPA and proxy `/api/` to the backend.

This compose file is a reproducible local/staging-like stack, not a complete production orchestration manifest.

### Creating users

Public registration is disabled outside local development. Create accounts on the server (the password is prompted for and never placed on the command line):

```bash
docker compose exec api python scripts/create_user.py --email you@company.com --full-name "Your Name" --role finance_director
```

## Testing

Backend unit/integration:

```bash
python -m pytest tests/unit tests/integration -v --cov=app --cov-report=term-missing
```

Static analysis:

```bash
ruff check .
black --check app tests alembic
mypy app
bandit -r app -x tests
pip-audit -r requirements.txt
```

Frontend:

```bash
npm run typecheck
npm run lint
npm test
npm run build
npm run test:e2e
npm run test:a11y
npm audit --audit-level=high
```

## Authentication

Access tokens are short-lived JWTs. Refresh tokens are persisted as sessions, rotated on refresh, and revocable through `/api/v1/auth/logout`. Protected requests resolve the current active user from PostgreSQL so a deactivated account or changed role does not remain authorized merely because an old token contains stale claims.

Public registration is disabled by default and fails closed in production.

## Approval execution

Approval resolution and financial execution are separate state transitions. Only explicit action types registered in `ApprovalCommandExecutor` can execute. The current executable command is `payment_execute`, and the backend re-checks permissions and entity state before execution.

## Audit

`audit_logs` is a durable append-only table with database-enforced update/delete protection and a hash chain. `/api/v1/audit/logs` queries it and `/api/v1/audit/verify` verifies chain integrity.

## SAP Business One

SAP is backend-only. The Service Layer client manages login/logout, safe read retries, SAP error normalization, and conservative mutation handling. Ambiguous mutation failures are surfaced as reconciliation-required and are not blindly replayed.

The current agent contract advertises only entities actually supported by the backend. Live SAP verification is documented in `SAP_LIVE_VERIFICATION.md` and has **not** been performed in the current sandbox.

## Documentation

- `ARCHITECTURE.md`
- `API_CONTRACT_MATRIX.md`
- `API_QA_MATRIX.md`
- `FRONTEND_QA_MATRIX.md`
- `SAP_INTEGRATION.md`
- `SAP_LIVE_VERIFICATION.md`
- `SECURITY_REVIEW.md`
- `FINAL_TECHNICAL_AUDIT.md`
- `FINAL_QA_REPORT.md`
- `PROJECT_STATUS_AND_ROADMAP.md`
- `docs/GO_LIVE_CHECKLIST.md` (what must be done and verified before real use)

## Production gates still requiring a controlled environment

Everything that could be built and checked offline has been. What remains needs a machine with internet access, Docker, PostgreSQL and (for SAP) an approved test company. `docs/GO_LIVE_CHECKLIST.md` lists each gate with the exact command and what a pass looks like.

Summary of the current position:

- AR, AP and General Ledger report amounts are never added across currencies. No exchange rates exist, so reports and balances are per currency.
- The approval inbox keeps approved, executing, failed and executed requests reachable, with exact counters.
- The rate limiter is held in one process. Run one API worker. A shared limiter is required before scaling out.
- Multi factor sign in and single sign on are not implemented.
- SAP: a read only connection probe and customer or vendor master data synchronization exist. Nothing has been verified against a real SAP tenant by this software.
- Not yet run by anyone: the full backend suite on PostgreSQL, the frontend typecheck, lint, Vitest and build with real dependencies, Playwright and axe, `pip-audit`, `npm audit`, and a Docker compose start.
