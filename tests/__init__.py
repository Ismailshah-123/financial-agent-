"""Test suite root. `unit/` tests individual functions/classes in
isolation (no DB, no network — fakes/mocks only). `integration/` tests
exercise real collaborators (a test Postgres database, the FastAPI app
via httpx.AsyncClient) and are slower/fewer by design (test pyramid)."""
