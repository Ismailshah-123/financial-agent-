# Go Live Checklist

Date: 2026-10-14. Read this with `FINAL_QA_REPORT.md` and `REMAINING_WORK_AND_ACCEPTANCE.md`.

The code changes needed for a single instance deployment are in the repository. The items below cannot be proven from a machine with no network, no Docker and no SAP tenant, so each one is a gate you complete and tick yourself. Nothing here has been run on your behalf.

## A. Run once on a machine with internet access (about 30 minutes)

Shortcut: `python scripts/dev.py setup`, then `python scripts/dev.py check --fix --e2e`. It runs the gates below that can run on a laptop and prints one pass or fail table, with the full output in `verify-report.txt`. Anything marked FAIL goes back to be fixed; nothing here is claimed to pass until that table says so.


| # | Gate | Command | Pass means |
|---|---|---|---|
| A1 | Lock frontend dependencies | `cd frontend && npm run lockfile`, then commit `package-lock.json` | File exists and installs with `npm ci`. If a pinned version in `package.json` does not exist on the registry, correct that version first. |
| A2 | Frontend checks | `cd frontend && npm ci && npm run check` | typecheck, eslint, vitest and `vite build` all exit 0 |
| A3 | Backend format | `black app tests alembic scripts && ruff check --fix .` then commit | CI Black and Ruff steps pass. The new Python was written to match Black but was never run through it. |
| A4 | Backend suite on PostgreSQL | `pip install -r requirements.txt -r requirements-dev.txt && alembic upgrade head && python -m pytest tests/unit tests/integration -v` | zero failures. Pay special attention to `test_financial_reports.py`, `test_approval_requests.py` and the new unit tests. |
| A5 | Static and dependency scans | `mypy app && bandit -r app && pip-audit -r requirements.txt && (cd frontend && npm audit --audit-level=high)` | no unaccepted findings |
| A6 | Browser tests | `cd frontend && npx playwright install --with-deps chromium && npx playwright test e2e/mocked.spec.ts e2e/accessibility.spec.ts` | pass. These use a fake backend, so they need no credentials. |
| A7 | Real backend browser journeys | start the stack, create a test user (section C), set `E2E_EMAIL` and `E2E_PASSWORD`, run `npm run test:e2e` | pass |
| A8 | Container build and start | `docker compose up --build`, open http://localhost:3000, sign in | both images build, `alembic upgrade head` succeeds on an empty database, `/api/v1/health/ready` returns 200 |
| A9 | Content Security Policy | open the app in Chrome with DevTools Console open and visit every page | no "Content-Security-Policy" violation messages. If one appears, adjust `frontend/nginx/default.conf`. |

## B. Configuration for the real environment

- [ ] `APP_ENVIRONMENT=production`. The application then refuses to start with debug on, public registration on, a placeholder secret or a JWT secret shorter than 32 characters.
- [ ] `SECURITY_JWT_SECRET_KEY`: 48 or more random characters from a secret manager. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- [ ] `SECURITY_ALLOW_PUBLIC_REGISTRATION=false`.
- [ ] `DB_PASSWORD` unique and strong. Use a managed PostgreSQL with automated backups and point in time recovery. Practise one restore before go live.
- [ ] `APP_CORS_ORIGINS` is the exact public HTTPS origin of the web app. No wildcards.
- [ ] TLS terminates in front of the web container. Have that layer send `Strict-Transport-Security`.
- [ ] `APP_TRUSTED_PROXY_HOPS` equals the number of reverse proxies you run in front of the API (1 for the bundled nginx). Leave it at 0 if clients can reach the API port directly, otherwise they could forge their address and dodge rate limits.
- [ ] Do not publish ports 5432, 6379, 6333 or 8000 to a network. The compose file binds them to 127.0.0.1 only.
- [ ] Run exactly one API worker and one API container until a shared rate limiter exists (see section E).
- [ ] LLM keys and `SAP_*` values are set only through the secret manager. They must never appear in `VITE_` variables, images or Git.
- [ ] Log shipping and alerting are in place for 5xx rates, failed logins and failed approval executions. The API logs structured JSON with request and correlation ids.

## C. First users

Public registration is off, so accounts are created on the server with the supplied command. The password is prompted for (twice, hidden) and never passes through the command line.

```bash
docker compose exec api python scripts/create_user.py \
  --email cfo@yourcompany.com --full-name "Chief Financial Officer" --role finance_director
```

- [ ] Create one `finance_director` for yourself and sign in.
- [ ] Create separate accounts per person. Use `auditor` for read only audit access, `approver` for people who only decide, `ap_clerk` and `ar_clerk` for data entry. Recording an approval needs `approval_request:action` (`finance_director`, `finance_manager`, `approver`, `super_admin`). Executing a payment also needs `payment:approve` (`finance_director`, `approver`, `super_admin`), so a `finance_manager` can decide but cannot move money.
- [ ] There is no screen for deactivating users or resetting passwords yet. Until one exists, do those directly in the database and record it. This is a known gap.

## D. Smoke test after deploy (15 minutes, a test company or empty system)

1. Sign in. The overview loads and nothing flashes before the sign in screen.
2. Open each workspace from the sidebar. Reload the browser on a customer detail URL and confirm it reopens the same customer.
3. Reports: with posted entries in two currencies the page must force a currency choice. Run a trial balance and download the CSV.
4. Approval inbox: approve one test recommendation, confirm the Awaiting execution tab now shows it after a page reload, execute it once, and confirm the audit log shows the approval and the execution with the same correlation chain.
5. Audit Center: press Verify chain and confirm it reports valid.
6. Sign out, then confirm that the browser back button does not reveal finance data.
7. Leave a signed in tab idle for the configured time (30 minutes by default) and confirm it signs out with an explanation.

## E. Known limits you are accepting by going live

These are real. They are not hidden and none of them is fixed by this delivery.

| Limit | Impact | Mitigation until fixed |
|---|---|---|
| Rate limiter is held in one process | Limits multiply with more workers | Run one API worker |
| No MFA or SSO | Password only sign in | Strong passwords, short idle timeout, restrict by network or VPN if possible |
| No user administration screen | Accounts are managed by command or SQL | Follow section C and keep a record |
| Audit chain verification reads the whole chain | Slow on very large logs | Run it on demand, not on a schedule, until it is made incremental |
| Failure evidence can be lost if the business transaction rolls back | A failed action may leave no audit row of the failure | Review the approval's `execution_error` and server logs for failed executions |
| An approval stuck in "executing" needs manual reconciliation | A crash mid execution leaves it locked | Check the payment record, then correct the state directly. The UI warns against retrying. |
| Tax, treasury, budgets, bank reconciliation, fraud, compliance and period close have no dedicated screens | Reachable only through AI Agents | Use the Agent Center |
| General ledger reports are single currency | One currency per report | By design: no exchange rates exist |
| SAP | Read only probe and customer or vendor master data only | Section F |

## F. SAP Business One

Nothing about SAP has been verified against a real tenant. Do not describe the integration as live until every box is ticked.

- [ ] Use an approved test company, never production, for the first runs.
- [ ] Set `SAP_ENABLED=true`, `SAP_SERVICE_LAYER_URL` (HTTPS), `SAP_COMPANY_DB`, `SAP_USERNAME`, `SAP_PASSWORD`. Keep `SAP_VERIFY_SSL=true`. If the Service Layer uses a private certificate authority, install that CA on the API host. Never disable verification.
- [ ] SAP Integration page: press Verify read only connection. Expect "Read check passed". Any other state is shown with its cause.
- [ ] Synchronize one test customer and one test vendor. Confirm each appears once in SAP. Run the same synchronization again and confirm no duplicate is created.
- [ ] Record the outcomes in `SAP_LIVE_VERIFICATION.md`.
- [ ] Invoices, payments and journal postings are not exposed through the UI. Enabling them needs approval bound execution and a reconciliation workflow first.

## G. Rollback

- Keep the previous image tags. Deploy by changing tags, not by rebuilding in place.
- Migrations are forward only in practice. Take a database backup immediately before each release that includes a migration. This delivery adds no migration.
- If a release must be reverted after payments were executed, reconcile those payments before and after the revert. Do not re revert blindly.
