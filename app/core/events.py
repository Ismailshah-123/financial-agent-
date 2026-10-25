"""
app.core.events
================
Domain event bus. This is the backbone of agent-to-agent communication:
instead of agents calling each other's Python methods directly (which
creates a tangled import graph and makes it impossible to add a new
agent without touching every existing one), agents publish domain
events ("invoice.received", "invoice.approved", "payment.failed") and
subscribe to the ones they care about.

DESIGN
------
`EventBus` is an abstract interface with one concrete implementation
today, `InMemoryEventBus` (asyncio-based pub/sub, single process — fine
for local dev and for a single-worker deployment). `BrokerSettings.provider`
in config.py already reserves the switch for `rabbitmq` / `kafka`
implementations; when those are added they satisfy the same `EventBus`
interface, so nothing above this module needs to change.

Every event is a `DomainEvent`: a typed envelope with an event name,
a payload, and provenance metadata (correlation id, timestamp, producer).
This event/payload separation (rather than raw dicts) is what lets
`app/agents` and `app/workers` be typed and testable.

USAGE
-----
    from app.core.events import get_event_bus, DomainEvent, EventType

    bus = get_event_bus()

    @bus.subscribe(EventType.INVOICE_RECEIVED)
    async def handle_invoice_received(event: DomainEvent) -> None:
        ...

    await bus.publish(DomainEvent(
        type=EventType.INVOICE_RECEIVED,
        payload={"invoice_id": "inv_123"},
        producer="invoice_processing_agent",
    ))
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from app.core.logging import get_correlation_id, get_logger

logger = get_logger(__name__)


class EventType(str, Enum):
    """Canonical domain event vocabulary. Add new event names here so
    producers and consumers can never drift on string literals."""

    # Documents
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_OCR_COMPLETED = "document.ocr_completed"

    # Invoices
    INVOICE_RECEIVED = "invoice.received"
    INVOICE_MATCHED = "invoice.matched"
    INVOICE_MATCH_FAILED = "invoice.match_failed"
    INVOICE_APPROVED = "invoice.approved"
    INVOICE_REJECTED = "invoice.rejected"

    # Payments
    PAYMENT_SCHEDULED = "payment.scheduled"
    PAYMENT_EXECUTED = "payment.executed"
    PAYMENT_FAILED = "payment.failed"

    # Agent lifecycle
    AGENT_DECISION_MADE = "agent.decision_made"
    AGENT_APPROVAL_REQUIRED = "agent.approval_required"
    AGENT_EXECUTION_FAILED = "agent.execution_failed"
    AGENT_ROLLBACK_TRIGGERED = "agent.rollback_triggered"

    # Workflow
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_REJECTED = "approval.rejected"
    APPROVAL_ESCALATED = "approval.escalated"


class DomainEvent(BaseModel):
    """Typed envelope for everything published on the bus."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: EventType
    payload: dict[str, Any]
    producer: str
    correlation_id: str = Field(default_factory=get_correlation_id)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


EventHandler = Callable[[DomainEvent], Awaitable[None]]


class EventBus(ABC):
    """Abstract pub/sub interface. Swap `InMemoryEventBus` for a
    RabbitMQ/Kafka-backed implementation without changing any caller."""

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None: ...

    @abstractmethod
    def subscribe(
        self, event_type: EventType
    ) -> Callable[[EventHandler], EventHandler]:
        """Decorator form: `@bus.subscribe(EventType.X)`."""
        ...

    @abstractmethod
    async def register(self, event_type: EventType, handler: EventHandler) -> None:
        """Imperative form, for when a decorator isn't convenient
        (e.g. registering handlers in a loop at startup)."""
        ...


class InMemoryEventBus(EventBus):
    """
    Single-process asyncio pub/sub. Handlers run concurrently via
    `asyncio.gather`; a handler exception is logged and does NOT prevent
    other handlers for the same event from running (one agent's bug
    should never silently swallow another agent's notification).

    Not durable — events are lost on process restart. That tradeoff is
    fine for local dev and is exactly why `BrokerSettings.provider`
    exists: production deployments switch this to a RabbitMQ/Kafka-backed
    `EventBus` implementation for durability and cross-process delivery.
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)

    async def publish(self, event: DomainEvent) -> None:
        logger.info(
            "event_published",
            event_type=event.type.value,
            event_id=event.event_id,
            producer=event.producer,
        )
        handlers = self._handlers.get(event.type, [])
        if not handlers:
            return

        async def _run_safely(handler: EventHandler) -> None:
            try:
                await handler(event)
            except Exception:  # noqa: BLE001 — deliberately isolate handler failures
                logger.error(
                    "event_handler_failed",
                    event_type=event.type.value,
                    event_id=event.event_id,
                    handler=getattr(handler, "__name__", repr(handler)),
                    exc_info=True,
                )

        await asyncio.gather(*(_run_safely(h) for h in handlers))

    def subscribe(
        self, event_type: EventType
    ) -> Callable[[EventHandler], EventHandler]:
        def decorator(handler: EventHandler) -> EventHandler:
            self._handlers[event_type].append(handler)
            return handler

        return decorator

    async def register(self, event_type: EventType, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)


_event_bus_singleton: EventBus | None = None


def get_event_bus() -> EventBus:
    """Process-wide event bus singleton. In a later phase this factory
    is what inspects `settings.broker.provider` and returns a
    RabbitMQ/Kafka-backed implementation instead."""
    global _event_bus_singleton
    if _event_bus_singleton is None:
        _event_bus_singleton = InMemoryEventBus()
    return _event_bus_singleton
