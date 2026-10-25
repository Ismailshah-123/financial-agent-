"""
app.services.approval_service
=================================
Reads and resolves persisted `ApprovalRequestRecord` rows.
`create_from_decision` is called from exactly one place —
`BaseAgent.run()` — never by an individual agent; see that method for
why this belongs at the framework level, not per-agent.

APPROVING HERE NEVER APPLIES THE UNDERLYING RECOMMENDATION
------------------------------------------------------------------------------
`approve()` only flips this row's own status to APPROVED and records
who/when/why. It does NOT call `VendorService.apply_risk_assessment`,
`PaymentService`, `BankReconciliationService.confirm_match`, or
anything else the original decision recommended — same "AI never
transacts without approval" boundary as everywhere else in this
platform, just made explicit here too: approving the RECORD of a
recommendation and actually CARRYING OUT that recommendation are two
different actions, and conflating them would mean a click on "approve"
silently executes a financial action with no further confirmation.
Carrying out an approved recommendation is a separate, explicit call to
whichever service the original agent's decision pointed at.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import AgentDecision
from app.core.constants import ApprovalExecutionStatus, UserRole
from app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import get_audit_logger, get_logger
from app.db.models.approval_request import ApprovalRequestRecord
from app.repositories.approval_request_repository import ApprovalRequestRepository
from app.services.approval_views import public_execution_error


logger = get_logger(__name__)

class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ApprovalRequestRepository(session)

    async def create_from_decision(
        self, decision: AgentDecision, *, correlation_id: str, actor_id: str
    ) -> ApprovalRequestRecord:
        record = ApprovalRequestRecord(
            id=uuid.uuid4(),
            decision_id=decision.decision_id,
            agent_type=decision.agent_type.value,
            correlation_id=correlation_id,
            actor_id=actor_id,
            risk_level=decision.risk_level.value,
            summary=decision.summary,
            decision_json=decision.model_dump(mode="json"),
            status="pending",
            action_type=decision.action_type.value if decision.action_type else None,
            action_payload=decision.action_payload,
            execution_status=(
                ApprovalExecutionStatus.EXECUTION_PENDING.value
                if decision.action_type
                else ApprovalExecutionStatus.NOT_APPLICABLE.value
            ),
        )
        if decision.action_type:
            record.idempotency_key = f"approval:{record.id}:execute"
        return await self.repository.add(record)

    async def list_pending(
        self, *, agent_type: str | None = None, offset: int = 0, limit: int = 25
    ) -> list[ApprovalRequestRecord]:
        return await self.repository.list_pending(
            agent_type=agent_type, offset=offset, limit=limit
        )

    async def list_view(
        self,
        *,
        view: str = "pending",
        agent_type: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> list[ApprovalRequestRecord]:
        return await self.repository.list_view(
            view=view, agent_type=agent_type, offset=offset, limit=limit
        )

    async def summary(self) -> dict[str, int]:
        return await self.repository.summary_counts()

    async def approve(
        self, request_id: uuid.UUID, *, actor_id: str, notes: str | None
    ) -> ApprovalRequestRecord:
        return await self._resolve(request_id, status="approved", actor_id=actor_id, notes=notes)

    async def reject(
        self, request_id: uuid.UUID, *, actor_id: str, reason: str
    ) -> ApprovalRequestRecord:
        if not reason or not reason.strip():
            raise ValidationError("A reason is required to reject an approval request.")
        return await self._resolve(request_id, status="rejected", actor_id=actor_id, notes=reason)

    async def _resolve(
        self, request_id: uuid.UUID, *, status: str, actor_id: str, notes: str | None
    ) -> ApprovalRequestRecord:
        record = await self.repository.get_by_id_for_update(request_id)
        if record is None:
            raise NotFoundError(
                f"ApprovalRequestRecord with id {request_id} not found.",
                details={"model": "ApprovalRequestRecord", "id": str(request_id)},
            )
        if record.status != "pending":
            raise ConflictError(
                f"Approval request {request_id} is already {record.status} "
                f"(resolved {record.resolved_at}).",
                details={"approval_request_id": str(request_id), "current_status": record.status},
            )

        record.status = status
        record.resolved_at = datetime.now(timezone.utc)
        record.resolved_by_id = uuid.UUID(actor_id) if _is_uuid(actor_id) else None
        record.resolution_notes = notes
        await self.session.flush()
        await get_audit_logger().record(
            session=self.session,
            actor_id=actor_id,
            action=f"approval_request.{status}",
            resource_type="approval_request",
            resource_id=str(record.id),
            outcome="success",
            metadata={"agent_type": record.agent_type, "decision_id": record.decision_id},
        )
        return record

    async def execute(
        self, request_id: uuid.UUID, *, actor_id: str, actor_role: UserRole
    ) -> ApprovalRequestRecord:
        from app.services.approval_execution_service import ApprovalCommandExecutor

        record = await self.repository.get_by_id_for_update(request_id)
        if record is None:
            raise NotFoundError(
                f"ApprovalRequestRecord with id {request_id} not found.",
                details={"model": "ApprovalRequestRecord", "id": str(request_id)},
            )
        if record.status != "approved":
            raise ConflictError(
                f"Approval request {request_id} must be approved before execution.",
                details={"approval_request_id": str(request_id), "current_status": record.status},
            )
        if not record.action_type:
            raise ConflictError(
                "This approval has no registered executable action. No financial action was performed.",
                details={"approval_request_id": str(request_id), "execution_status": record.execution_status},
            )
        if not record.idempotency_key:
            record.idempotency_key = f"approval:{record.id}:execute"
            await self.session.flush()
        if record.execution_status == ApprovalExecutionStatus.EXECUTED.value:
            return record
        if record.execution_status == ApprovalExecutionStatus.EXECUTING.value:
            raise ConflictError("This approval is already executing.")

        record.execution_status = ApprovalExecutionStatus.EXECUTING.value
        record.execution_attempted_at = datetime.now(timezone.utc)
        record.execution_error = None
        await self.session.flush()

        try:
            result = await ApprovalCommandExecutor(self.session).execute(
                action_type=record.action_type,
                payload=record.action_payload,
                actor_id=actor_id,
                actor_role=actor_role,
            )
        except AuthorizationError:
            record.execution_status = ApprovalExecutionStatus.EXECUTION_PENDING.value
            record.execution_error = "Execution permission check failed."
            await self.session.flush()
            await get_audit_logger().record(
                session=self.session,
                actor_id=actor_id,
                action="approval_request.execute",
                resource_type="approval_request",
                resource_id=str(record.id),
                outcome="denied",
                metadata={"action_type": record.action_type, "idempotency_key": record.idempotency_key},
            )
            raise
        except Exception as exc:
            logger.error(
                "approval_execution_failed",
                approval_request_id=str(record.id),
                action_type=record.action_type,
                exc_info=True,
            )
            record.execution_status = ApprovalExecutionStatus.FAILED.value
            record.execution_error = public_execution_error(exc)
            await self.session.flush()
            await get_audit_logger().record(
                session=self.session,
                actor_id=actor_id,
                action="approval_request.execute",
                resource_type="approval_request",
                resource_id=str(record.id),
                outcome="failed",
                metadata={
                    "action_type": record.action_type,
                    "idempotency_key": record.idempotency_key,
                    "error": str(exc)[:500],
                },
            )
            raise

        record.execution_status = ApprovalExecutionStatus.EXECUTED.value
        record.executed_at = datetime.now(timezone.utc)
        record.execution_result = result
        await self.session.flush()
        await get_audit_logger().record(
            session=self.session,
            actor_id=actor_id,
            action="approval_request.execute",
            resource_type="approval_request",
            resource_id=str(record.id),
            outcome="success",
            metadata={
                "action_type": record.action_type,
                "idempotency_key": record.idempotency_key,
                "result": result,
            },
        )
        return record


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
