"""
app.db.init_db
===============
Local-development table bootstrap.

`create_all()` is a dev/CI convenience — it inspects `Base.metadata` and
creates any tables that don't exist. It never drops or alters existing
tables, which makes it unsafe for schema evolution.

PRODUCTION AND STAGING MUST USE ALEMBIC MIGRATIONS, NOT THIS FUNCTION.
This function exists purely so a fresh local Postgres can be stood up
with `python -m app.db.init_db` while domain models are still being
designed, before the first Alembic migration is authored (next phase).
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.db.base import Base
from app.db.session import engine

# Required so Base.metadata is populated before create_all() runs —
# see app/db/models/__init__.py for why this import must happen.
import app.db.models  # noqa: F401

logger = get_logger(__name__)


async def create_all() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("db_tables_created", tables=list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    asyncio.run(create_all())
