"""
app.workers.tasks
====================
Celery tasks — used to run agents outside the HTTP request/response
cycle: batch/scheduled re-matching, or any caller that shouldn't block
on an LLM round-trip. `app.api.v1.agents` runs the AP agent inline for
the common single-invoice case; this task exists for the batch/async
case (e.g. a nightly job re-checking every invoice still in
`MATCH_FAILED`).

Each task opens its own short-lived DB session (`session_scope()`,
which commits on success / rolls back on exception) since Celery
workers are separate OS processes from the FastAPI app and cannot share
its request-scoped sessions.

WHY `asyncio.run` INSIDE A SYNC TASK
----------------------------------------
Celery's default (prefork) worker pool runs tasks as plain synchronous
functions — there is no event loop already running in a worker process.
`asyncio.run(...)` is the standard bridge: it spins up a fresh event
loop for the duration of this one task and tears it down afterward. If
this ever moves to Celery's asyncio-aware `gevent`/`eventlet` pools,
this bridge is the one place that would need to change.
"""

from __future__ import annotations

import asyncio

from app.agents.accounts_payable.agent import AccountsPayableAgent
from app.agents.schemas import AgentContext
from app.core.constants import UserRole
from app.core.logging import get_logger
from app.db.session import session_scope
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="agents.run_accounts_payable", bind=True, max_retries=2)
def run_accounts_payable_agent_task(
    self,
    *,
    invoice_id: str,
    actor_id: str,
    actor_role: str,
    correlation_id: str,
    tenant_id: str = "default",
) -> dict:
    """Synchronous Celery entrypoint. Returns the `AgentResult` as a
    plain JSON-serializable dict (Celery result backends store plain
    data, not Pydantic model instances)."""
    return asyncio.run(
        _run_async(
            invoice_id=invoice_id,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
        )
    )


async def _run_async(
    *,
    invoice_id: str,
    actor_id: str,
    actor_role: str,
    correlation_id: str,
    tenant_id: str,
) -> dict:
    async with session_scope() as session:
        agent = AccountsPayableAgent(session)
        context = AgentContext(
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            input_payload={"invoice_id": invoice_id},
        )
        result = await agent.run(context, actor_role=UserRole(actor_role))
        logger.info(
            "celery_agent_run_completed",
            invoice_id=invoice_id,
            status=result.status.value,
        )
        return result.model_dump(mode="json")
