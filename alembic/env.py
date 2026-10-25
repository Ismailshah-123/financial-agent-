"""
alembic/env.py
===============
Wires Alembic to the project's own settings and declarative base instead
of a hardcoded URL, so migrations always target the same database the
app itself would connect to. Uses the SYNC database URL
(`settings.database.sync_url`, psycopg2) — Alembic's migration runner is
sync; the app's runtime engine (asyncpg, in app/db/session.py) is
separate and unaffected.

IMPORTANT: as domain models are added (next phase, in a future
`app/db/models/` package), import them here so `Base.metadata` is
populated and `alembic revision --autogenerate` can detect them. This
file does not import any domain models yet because none exist yet.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.base import Base

# --- Alembic Config object, provides access to values in alembic.ini ---
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the URL from alembic.ini with the app's own settings so the
# two can never drift.
config.set_main_option("sqlalchemy.url", settings.database.sync_url)

# Importing app.db.models populates Base.metadata with every table and
# resolves the string-based relationship() references between models
# (see app/db/models/__init__.py for why this import is required here).
import app.db.models  # noqa: F401,E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL scripts without a live DB connection
    (`alembic upgrade head --sql`)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection (the normal path)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
