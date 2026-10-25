"""
app.api
=======
HTTP interface layer. Routers here translate HTTP requests into calls
against `app.services`, and translate `app.core.exceptions` back into
JSON responses (via the exception handlers registered in app.main).

Versioned under `app.api.v1` so a breaking v2 can be introduced later
without disturbing existing integrations (including a future SAP
Business One integration that will depend on API stability).
"""
