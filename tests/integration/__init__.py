"""Integration tests: exercise real collaborators (a real Postgres
database via the app's own async engine, and the actual FastAPI app via
an in-process ASGI client — see conftest.py for setup requirements,
most importantly: point DB_NAME at a dedicated test database before
running these).

Modules:
    conftest.py       — schema create/drop fixtures, the ASGI test client
    helpers.py          — register_and_login / auth_headers
    test_auth_flow.py    — registration, login, refresh, and their error paths
    test_ap_flow.py       — the full vendor -> PO -> GRPO -> invoice ->
                           agent -> approval -> payment flow end-to-end,
                           plus over-receipt rejection and duplicate-
                           invoice risk escalation
    test_ar_flow.py        — customer -> AR invoice -> send -> agent ->
                           credit memo issuance/application end-to-end,
                           plus over-credit-limit risk escalation and
                           over-balance credit memo rejection
"""
