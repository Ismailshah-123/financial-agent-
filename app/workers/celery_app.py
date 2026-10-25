"""
app.workers.celery_app
=========================
The Celery application instance. Run a worker with:

    celery -A app.workers.celery_app worker --loglevel=info

NOTE ON BROKER CHOICE: this uses `settings.redis.url` as both Celery's
broker and result backend — a separate concern from
`settings.broker` (`app.core.config.BrokerSettings`), which configures
the *domain event bus* (`app.core.events`), not Celery. It's entirely
normal, and common in this kind of architecture, for Celery to run on
Redis while the domain event bus later moves to RabbitMQ/Kafka — they
solve different problems (background task execution vs. agent-to-agent
domain events) and don't need to share infrastructure.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "finance_ai_platform",
    broker=settings.redis.url,
    backend=settings.redis.url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.app.timezone,
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # hard kill a task after 5 minutes
    task_soft_time_limit=270,
    worker_prefetch_multiplier=1,  # fair dispatch for long-ish agent tasks
    result_expires=86400,
)
