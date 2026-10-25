from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ApprovalActionType, Permission
from app.core.security import role_has_permission
from app.core.constants import UserRole
from app.core.exceptions import AuthorizationError, ValidationError
from app.core.logging import get_logger
from app.repositories.payment_repository import PaymentRepository
from app.services.payment_service import PaymentService

logger = get_logger(__name__)


@dataclass(frozen=True)
class CommandDefinition:
    action_type: ApprovalActionType
    required_permission: Permission
    executor: Callable[..., Awaitable[dict[str, Any]]]


class ApprovalCommandExecutor:
    """Allowlisted, typed approval command dispatcher.

    AI output is never interpreted as a Python method name. Each command has
    a fixed action type and validates its payload before calling a known
    service. The registry is intentionally small; unsupported approvals stay
    human-reviewable but non-executable until an explicit command is added.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.payment_repository = PaymentRepository(session)
        self.payment_service = PaymentService(session)
        self._definitions = {
            ApprovalActionType.PAYMENT_EXECUTE: CommandDefinition(
                action_type=ApprovalActionType.PAYMENT_EXECUTE,
                required_permission=Permission.PAYMENT_APPROVE,
                executor=self._execute_payment,
            )
        }

    async def execute(
        self, *, action_type: str, payload: dict[str, Any], actor_id: str, actor_role: UserRole
    ) -> dict[str, Any]:
        try:
            command_type = ApprovalActionType(action_type)
        except ValueError as exc:
            raise ValidationError(
                f"Unsupported approval action type '{action_type}'."
            ) from exc
        definition = self._definitions.get(command_type)
        if definition is None:
            raise ValidationError(f"No execution command is registered for '{action_type}'.")
        if not role_has_permission(actor_role, definition.required_permission):
            raise AuthorizationError(
                f"Actor role '{actor_role.value}' is not authorized for '{action_type}'."
            )
        return await definition.executor(payload=payload, actor_id=actor_id)

    async def _execute_payment(
        self, *, payload: dict[str, Any], actor_id: str
    ) -> dict[str, Any]:
        payment_id_raw = payload.get("payment_id")
        if not payment_id_raw:
            raise ValidationError("payment_execute requires payload.payment_id.")
        try:
            payment_id = uuid.UUID(str(payment_id_raw))
        except ValueError as exc:
            raise ValidationError("payment_execute payload.payment_id must be a UUID.") from exc

        payment = await self.payment_repository.get_by_id_or_raise(payment_id)
        if payment.status == "executed":
            return {
                "payment_id": str(payment.id),
                "status": payment.status,
                "bank_reference": payment.bank_reference,
                "idempotent_replay": True,
            }

        result = await self.payment_service.execute_payment(payment_id, actor_id=actor_id)
        return {
            "payment_id": str(result.id),
            "status": result.status,
            "bank_reference": result.bank_reference,
            "idempotent_replay": False,
        }
