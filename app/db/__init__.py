"""
app.db
======
Database layer: SQLAlchemy declarative base + reusable mixins, the async
engine/session factory, and the FastAPI `get_db` dependency.

This package deliberately contains NO domain models (Invoice, Vendor,
JournalEntry, etc.). Those live in `app/schemas` (Pydantic I/O shapes)
and a future `app/db/models/` package (SQLAlchemy ORM models), added in
the next compatibility-audit phase (core -> db -> schemas -> repositories
-> ...). Keeping `app/db` model-free at this stage means the foundation
can be reviewed and stabilized independently of any single domain's
schema decisions.
"""
