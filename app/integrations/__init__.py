"""
app.integrations
==================
HTTP clients for external systems this platform talks to — as opposed
to `app.repositories` (internal database access) or `app.services`
(internal business logic). The distinction matters: an integrations
client knows how to speak a third-party system's protocol (auth,
request/response shapes, error codes) and nothing about this
platform's own domain models; the mapping between the two lives in
each integration's `mappers.py`, and orchestration (when to sync, what
to do on conflict) lives in `app.services` (e.g.
`app.services.sap_sync_service`), not here.

Currently: `sap/` (SAP Business One Service Layer).
"""
