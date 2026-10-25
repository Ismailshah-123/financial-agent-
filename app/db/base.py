"""
app.db.base
===========
SQLAlchemy 2.0 declarative base plus reusable mixins that every domain
model (Invoice, Vendor, JournalEntry, ...) will compose from in the next
phase.

MIXINS
------
- `UUIDPrimaryKeyMixin`: UUID primary keys (not auto-increment ints) —
  required for a system that will eventually sync ids with SAP Business
  One and other external systems without collision risk.
- `TimestampMixin`: `created_at` / `updated_at`, server-side defaults so
  they're correct even for rows inserted outside the ORM (bulk loads,
  SAP sync jobs).
- `SoftDeleteMixin`: `deleted_at` nullable column + `is_deleted` property.
  Finance records are never hard-deleted (audit requirement) — "deleting"
  an invoice sets this column, and repository-layer queries filter it out
  by default.
- `AuditMixin`: `created_by_id` / `updated_by_id`, so every row records
  which user or agent produced it, independent of the free-text audit
  log stream in app.core.logging (that log explains *why*; these columns
  make *who* queryable directly on the record).

All future models: `class Invoice(Base, UUIDPrimaryKeyMixin, TimestampMixin,
SoftDeleteMixin, AuditMixin): ...`
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Root declarative base. All ORM models inherit from this (directly
    or via the mixins below) so Alembic's autogenerate can discover them
    from a single `Base.metadata`."""

    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class AuditMixin:
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
