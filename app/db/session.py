"""
app.db.session
===============
Async SQLAlchemy engine + session factory, and the FastAPI dependency
(`get_db`) every route/service uses to obtain a scoped session.

WHY A CONTEXT-MANAGED SESSION PER REQUEST
-------------------------------------------
`get_db` yields one `AsyncSession` per request and guarantees it is
closed (and rolled back on error) when the request finishes, regardless
of which code path raised. This is the standard FastAPI pattern and is
what prevents connection-pool exhaustion under load — the single most
common production incident in FastAPI+SQLAlchemy apps that skip it.

Repositories and services never construct their own session; they
receive one via `Depends(get_db)` (in routes) or as an explicit
constructor argument (in services/agents), which is also what makes
them unit-testable with an in-memory/test database session.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine: AsyncEngine = create_async_engine(
    settings.database.async_url,
    echo=settings.database.echo_sql,
    pool_size=settings.database.pool_size,
    max_overflow=settings.database.max_overflow,
    pool_timeout=settings.database.pool_timeout_seconds,
    pool_pre_ping=True,  # avoids "server closed the connection unexpectedly" after idle
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: `session: AsyncSession = Depends(get_db)`."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Non-FastAPI context manager for the same pattern — used by Celery
    workers, scripts, and Alembic-adjacent tooling where there's no
    dependency injection container.

        async with session_scope() as session:
            ...
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engine() -> None:
    """Call on application shutdown to cleanly close all pooled
    connections."""
    await engine.dispose()
