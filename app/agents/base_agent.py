"""
app.agents.base_agent
======================
`BaseAgent` is the contract every specialized agent (Accounts Payable,
Fraud Detection, Tax, Finance Director, ...) implements. It is the
piece of the "team of senior architects" design that turns 20 unrelated
agent implementations into one predictable system: any agent can be
invoked, monitored, retried, and audited the same way, because
`BaseAgent.run()` — not each subclass — owns error handling, timing,
event publication, and approval gating.

WHAT A SUBCLASS WRITES
------------------------
Subclasses implement exactly one method: `_execute(context) -> list[AgentDecision]`.
That's the agent's actual domain logic (call the LLM, run OCR, do the
3-way match, whatever). Everything else — turning that into a timed,
typed, published `AgentResult`; catching and classifying failures;
persisting and emitting `AGENT_APPROVAL_REQUIRED` events for decisions
that need a human — is handled once, here.

WHY THIS SHAPE
--------------
- `required_permission`: declared per-agent, checked before `_execute`
  ever runs. An agent that isn't authorized for the caller's role never
  executes — this is enforced structurally, not by the agent remembering
  to check.
- `run()` never lets a subclass's exception propagate as a bare
  traceback to the caller: it's caught, logged, converted into a
  `AgentExecutionError`-classified `AgentResult` with status FAILED, and
  an `AGENT_EXECUTION_FAILED` event is published so other agents /
  monitoring can react. Callers always get a well-formed `AgentResult`.
- Decisions with `requires_approval=True` are automatically turned into
  `ApprovalRequest`s, published as `AGENT_APPROVAL_REQUIRED` events, AND
  persisted as a real `ApprovalRequestRecord` row (see
  `app.services.approval_service` — added when the platform's first
  approval-inbox frontend work made "the event was transient and nothing
  ever queried it later" an actual, not just theoretical, problem)
  rather than being left for the subclass to remember to do — this is
  the code-level enforcement of "AI must never perform financial
  transactions without approval."
- `rollback()` is a separate, explicit method (not called automatically)
  because rolling back is itself a decision with consequences — the
  approval-workflow / orchestrating caller decides when to invoke it,
  typically after an `AGENT_EXECUTION_FAILED` or a rejected approval.

CONCRETE AGENTS
----------------
The first concrete implementation (Accounts Payable) is the next build
step per the agreed order: foundation now, one fully production-grade
agent next, then replicate the pattern per `AgentType`.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AgentType, Permission, UserRole
from app.core.events import DomainEvent, EventType, get_event_bus
from app.core.exceptions import AgentExecutionError
from app.core.logging import get_logger
from app.core.security import role_has_permission
from app.agents.schemas import (
    AgentContext,
    AgentDecision,
    AgentExecutionStatus,
    AgentResult,
    ApprovalRequest,
)
from app.services.approval_service import ApprovalService

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Abstract base class for every specialized finance agent."""

    #: Must be overridden by every subclass with its entry from AgentType.
    agent_type: AgentType

    #: Permission required to invoke this agent at all. Fine-grained,
    #: per-decision authorization (e.g. approval limits) happens on the
    #: `AgentDecision` output, not here.
    required_permission: Permission = Permission.AGENT_INVOKE

    def __init__(self, session: AsyncSession) -> None:
        if not hasattr(self, "agent_type"):
            raise TypeError(
                f"{type(self).__name__} must set the `agent_type` class attribute."
            )
        self.session = session
        self._approval_service = ApprovalService(session)
        self._event_bus = get_event_bus()

    # ------------------------------------------------------------------
    # Public entrypoint — subclasses never override this.
    # ------------------------------------------------------------------
    async def run(self, context: AgentContext, *, actor_role: UserRole) -> AgentResult:
        started_at = datetime.now(timezone.utc)
        start_perf = time.perf_counter()

        if not role_has_permission(actor_role, self.required_permission):
            return self._failed_result(
                started_at=started_at,
                start_perf=start_perf,
                error_message=(
                    f"Role '{actor_role.value}' is not permitted to invoke "
                    f"agent '{self.agent_type.value}'."
                ),
            )

        logger.info(
            "agent_run_started",
            agent_type=self.agent_type.value,
            correlation_id=context.correlation_id,
            actor_id=context.actor_id,
        )

        try:
            decisions = await self._execute(context)
        except Exception as exc:  # noqa: BLE001 — classified & re-surfaced below
            logger.error(
                "agent_run_failed",
                agent_type=self.agent_type.value,
                correlation_id=context.correlation_id,
                exc_info=True,
            )
            await self._event_bus.publish(
                DomainEvent(
                    type=EventType.AGENT_EXECUTION_FAILED,
                    payload={
                        "agent_type": self.agent_type.value,
                        "error": str(exc),
                    },
                    producer=self.agent_type.value,
                    correlation_id=context.correlation_id,
                )
            )
            return self._failed_result(
                started_at=started_at,
                start_perf=start_perf,
                error_message=str(exc),
            )

        await self._publish_decisions(context, decisions)

        status = (
            AgentExecutionStatus.AWAITING_APPROVAL
            if any(d.requires_approval for d in decisions)
            else AgentExecutionStatus.SUCCESS
        )
        completed_at = datetime.now(timezone.utc)
        result = AgentResult(
            agent_type=self.agent_type,
            status=status,
            decisions=decisions,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=round((time.perf_counter() - start_perf) * 1000, 2),
        )

        logger.info(
            "agent_run_completed",
            agent_type=self.agent_type.value,
            correlation_id=context.correlation_id,
            status=status.value,
            decision_count=len(decisions),
            duration_ms=result.duration_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------
    @abstractmethod
    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        """
        Domain logic for this agent. Must return at least one
        `AgentDecision` (an agent that concludes nothing should still
        return a LOW-risk decision documenting that, for auditability —
        never an empty list from a run that "did something").

        Raise any exception to signal failure; `run()` will catch,
        classify, log, and publish it. Do not catch-and-swallow errors
        here — let `run()`'s centralized handling do that.
        """
        raise NotImplementedError

    async def rollback(self, decision: AgentDecision) -> None:
        """
        Execute the compensating action described in
        `decision.rollback_strategy`. Not called automatically by `run()` —
        invoked explicitly by the orchestrating caller (Finance Director
        agent, approval-workflow engine, or an operator) once a decision
        needs to be undone.

        Base implementation raises if the decision was declared
        non-reversible; subclasses that support rollback for specific
        decision types override this.
        """
        if not decision.rollback_strategy.is_reversible:
            raise AgentExecutionError(
                f"Decision {decision.decision_id} was declared non-reversible "
                f"({decision.rollback_strategy.compensating_action}); it cannot "
                f"be rolled back automatically and requires manual reconciliation.",
                details={"decision_id": decision.decision_id},
            )
        raise NotImplementedError(
            f"{type(self).__name__} has not implemented rollback() for a "
            f"reversible decision — this is a bug, not a valid end state."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _publish_decisions(
        self, context: AgentContext, decisions: list[AgentDecision]
    ) -> None:
        for decision in decisions:
            await self._event_bus.publish(
                DomainEvent(
                    type=EventType.AGENT_DECISION_MADE,
                    payload={"decision": decision.model_dump(mode="json")},
                    producer=self.agent_type.value,
                    correlation_id=context.correlation_id,
                )
            )
            if decision.requires_approval:
                approval_request = ApprovalRequest(decision=decision)
                await self._event_bus.publish(
                    DomainEvent(
                        type=EventType.AGENT_APPROVAL_REQUIRED,
                        payload={
                            "approval_request": approval_request.model_dump(mode="json")
                        },
                        producer=self.agent_type.value,
                        correlation_id=context.correlation_id,
                    )
                )
                # The event above is transient (in-process pub/sub only —
                # nothing replays it after the fact). This is the actual
                # persistence: a real row an approval inbox can query
                # later, regardless of whether anything was listening on
                # the event bus at the moment this ran. See
                # ApprovalService's module docstring for why approving
                # this row never applies the decision itself.
                await self._approval_service.create_from_decision(
                    decision, correlation_id=context.correlation_id, actor_id=context.actor_id
                )

    def _failed_result(
        self, *, started_at: datetime, start_perf: float, error_message: str
    ) -> AgentResult:
        completed_at = datetime.now(timezone.utc)
        return AgentResult(
            agent_type=self.agent_type,
            status=AgentExecutionStatus.FAILED,
            decisions=[],
            error_message=error_message,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=round((time.perf_counter() - start_perf) * 1000, 2),
        )
