"""
app.api.v1
==========
Version 1 of the public API. `router.py` (added alongside the first
domain module) aggregates every sub-router (health, auth, invoices,
agents, ...) into one `APIRouter` that `app.main` mounts under
`settings.app.api_v1_prefix`.
"""
