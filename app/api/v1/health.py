"""
app.api.v1.health
==================
Liveness and readiness probes.

    GET /api/v1/health/live   -> process is up (no dependency checks;
                                  used by orchestrators like Kubernetes
                                  to decide whether to restart the pod)
    GET /api/v1/health/ready  -> process AND its critical dependencies
                                  (database, at minimum) are reachable;
                                  used to decide whether to route traffic
                                  to this instance

Kept dependency-free and fast on purpose — a probe endpoint that itself
becomes slow or flaky under load defeats its own purpose.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.config import settings
from app.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness() -> dict:
    return {"status": "alive", "service": settings.app.name}


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness(session: AsyncSession = Depends(get_db)) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ready", "service": settings.app.name}
