from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.schemas.common import APIModel


class AuditLogRead(APIModel):
    id: uuid.UUID
    sequence_number: int
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    outcome: str
    correlation_id: str
    metadata: dict[str, Any]
    prev_hash: str
    entry_hash: str
    created_at: datetime

    @classmethod
    def from_record(cls, record) -> "AuditLogRead":
        return cls(
            id=record.id,
            sequence_number=record.sequence_number,
            actor_id=record.actor_id,
            action=record.action,
            resource_type=record.resource_type,
            resource_id=record.resource_id,
            outcome=record.outcome,
            correlation_id=record.correlation_id,
            metadata=record.metadata_json,
            prev_hash=record.prev_hash,
            entry_hash=record.entry_hash,
            created_at=record.created_at,
        )


class AuditLogVerifyRead(APIModel):
    valid: bool
    checked_entries: int
    first_failure_sequence: int | None = None
    message: str
