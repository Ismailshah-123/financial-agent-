"""
app.core.logging
=================
Structured (JSON) application logging + a dedicated, tamper-evident audit
log channel.

WHY TWO LOG CHANNELS
---------------------
Application logs (`get_logger(__name__)`) are for operators: debugging,
performance, error traces. They can be sampled, rotated, and are not
a compliance artifact.

The audit log (`get_audit_logger()`) is a compliance artifact: every
financial decision, approval, and agent action must be recorded with
who/what/when/why and must NOT be mutated after the fact. In this
foundation phase it writes structured JSON lines with a monotonic
sequence + hash-chain field (`prev_hash`) so tampering with a historical
line breaks the chain — the actual persistence backend (append-only DB
table with DB-level revoke-UPDATE permission, or a WORM store) is wired
up in the db/audit module in a later phase. The interface here is stable
so that swap-in doesn't ripple through every call site.

USAGE
-----
    from app.core.logging import get_logger, get_audit_logger, bind_context

    logger = get_logger(__name__)
    logger.info("invoice_processed", invoice_id=inv.id, amount=inv.total)

    audit = get_audit_logger()
    audit.record(
        actor_id=user.id,
        action="invoice.approve",
        resource_type="invoice",
        resource_id=str(inv.id),
        outcome="success",
        metadata={"amount": str(inv.total)},
    )
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.audit_log import AUDIT_LOG_SEQUENCE, AuditChainState, AuditLog

# Context-local correlation id, set by the request-id middleware, so every
# log line emitted while handling a request/agent-run automatically carries
# it without threading it through every function signature.
_correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def bind_context(correlation_id: str) -> None:
    _correlation_id_ctx.set(correlation_id)


def get_correlation_id() -> str:
    return _correlation_id_ctx.get() or "unbound"


class _JsonFormatter(logging.Formatter):
    """Renders each log record as a single JSON line (structured logging
    that's directly ingestible by ELK/Datadog/CloudWatch)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        # Any extra kwargs passed via logger.info("msg", extra={...}) or the
        # StructuredLogger wrapper below get merged in.
        if hasattr(record, "extra_fields"):
            payload.update(record.extra_fields)  # type: ignore[attr-defined]
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class StructuredLogger:
    """Thin wrapper giving `logger.info("event_name", key=value, ...)`
    ergonomics (structlog-style) over the stdlib logger, without adding a
    hard dependency on structlog for this foundation phase."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _log(self, level: int, event: str, **fields: Any) -> None:
        self._logger.log(level, event, extra={"extra_fields": fields})

    def debug(self, event: str, **fields: Any) -> None:
        self._log(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self._log(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._log(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._log(logging.ERROR, event, **fields)

    def critical(self, event: str, **fields: Any) -> None:
        self._log(logging.CRITICAL, event, **fields)


_configured = False


def configure_logging() -> None:
    """Idempotent logging setup. Call once at process startup (main.py,
    worker entrypoint, Alembic env.py)."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.app.debug else logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.handlers = [handler]

    # Quiet noisy third-party loggers by default.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.database.echo_sql else logging.WARNING
    )

    _configured = True


def get_logger(name: str) -> StructuredLogger:
    configure_logging()
    return StructuredLogger(name)


class AuditLogger:
    """Durable append-only audit logger plus an operational log mirror.

    When a database session is supplied, the record and the hash-chain state
    are written in that same transaction as the business operation. A row
    lock serializes chain updates so concurrent requests cannot fork the
    chain. The database migration also installs an UPDATE/DELETE trigger,
    making audit records append-only at the database boundary.

    When no session is supplied, the logger falls back to the legacy
    process-local structured log path. Production business code should
    always pass its request session.
    """

    _CHAIN_STATE_ID = "global"

    def __init__(self) -> None:
        self._logger = logging.getLogger("audit")
        self._last_hash = "0" * 64
        self._sequence = 0

    async def record(
        self,
        *,
        session: AsyncSession | None = None,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_metadata = _sanitize_audit_metadata(metadata or {})
        timestamp = datetime.now(timezone.utc).isoformat()
        correlation_id = get_correlation_id()

        if session is None:
            self._sequence += 1
            sequence_number = self._sequence
            prev_hash = self._last_hash
            entry_id = str(uuid.uuid4())
            entry = _audit_entry_payload(
                entry_id=entry_id,
                sequence_number=sequence_number,
                timestamp=timestamp,
                correlation_id=correlation_id,
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome=outcome,
                metadata=safe_metadata,
                prev_hash=prev_hash,
            )
            entry_hash = _hash_audit_entry(entry)
            entry["entry_hash"] = entry_hash
            self._last_hash = entry_hash
            self._logger.info(json.dumps(entry, default=str))
            return entry

        state = await session.scalar(
            select(AuditChainState)
            .where(AuditChainState.id == self._CHAIN_STATE_ID)
            .with_for_update()
        )
        if state is None:
            state = AuditChainState(id=self._CHAIN_STATE_ID, last_hash="0" * 64)
            session.add(state)
            await session.flush()

        prev_hash = state.last_hash
        entry_id = uuid.uuid4()
        created_at = datetime.now(timezone.utc)

        # Take the sequence number explicitly BEFORE inserting, then compute the hash and insert the
        # row exactly once with its final hash. Two reasons:
        #   1. Reading a database-generated column off a just-flushed row triggers a lazy load,
        #      which async SQLAlchemy forbids (MissingGreenlet).
        #   2. audit_logs is append-only (migration 0012 installs an UPDATE/DELETE trigger), so the
        #      old "insert with a placeholder hash, then UPDATE entry_hash" sequence is rejected
        #      by the database. The chain-state row is locked above, so sequence order is safe.
        sequence_number = int(await session.scalar(select(AUDIT_LOG_SEQUENCE.next_value())))

        entry = _audit_entry_payload(
            entry_id=str(entry_id),
            sequence_number=sequence_number,
            timestamp=created_at.isoformat(),
            correlation_id=correlation_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            metadata=safe_metadata,
            prev_hash=prev_hash,
        )
        entry_hash = _hash_audit_entry(entry)

        session.add(
            AuditLog(
                id=entry_id,
                created_at=created_at,
                updated_at=created_at,
                sequence_number=sequence_number,
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome=outcome,
                correlation_id=correlation_id,
                metadata_json=safe_metadata,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
        )
        state.last_hash = entry_hash
        await session.flush()

        entry["entry_hash"] = entry_hash
        self._logger.info(json.dumps(entry, default=str))
        return entry


def _audit_entry_payload(**fields: Any) -> dict[str, Any]:
    return dict(fields)


def _hash_audit_entry(entry: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _sanitize_audit_metadata(value: Any) -> Any:
    """Redact common credential/token keys before durable audit storage."""
    secret_keys = {
        "password",
        "passcode",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "secret",
        "client_secret",
        "authorization",
        "cookie",
    }
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in secret_keys else _sanitize_audit_metadata(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_audit_metadata(item) for item in value]
    return value


_audit_logger_singleton: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger_singleton
    if _audit_logger_singleton is None:
        _audit_logger_singleton = AuditLogger()
    return _audit_logger_singleton