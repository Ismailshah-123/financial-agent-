from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import BigInteger, Sequence, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


AUDIT_LOG_SEQUENCE = Sequence("audit_log_sequence")


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable, append-only audit record.

    The database trigger installed by migration 0012 rejects UPDATE/DELETE.
    ``sequence_number`` orders entries according to the hash-chain lock held
    by AuditLogger, rather than wall-clock timestamps which can tie under load.
    """

    __tablename__ = "audit_logs"

    sequence_number: Mapped[int] = mapped_column(
        BigInteger, AUDIT_LOG_SEQUENCE, nullable=False, unique=True
    )
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AuditLog seq={self.sequence_number} action={self.action!r} "
            f"resource={self.resource_type}/{self.resource_id} outcome={self.outcome!r}>"
        )


class AuditChainState(Base):
    """Singleton state row used to serialize hash-chain append operations."""

    __tablename__ = "audit_chain_state"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_hash: Mapped[str] = mapped_column(String(64), nullable=False)
