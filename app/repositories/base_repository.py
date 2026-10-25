"""
app.repositories.base_repository
==================================
Generic CRUD repository that every concrete repository (`VendorRepository`,
`InvoiceRepository`, ...) inherits from, parameterized on its SQLAlchemy
model type. This is what keeps `app.services` and `app.agents` free of
raw SQLAlchemy `select()` statements for the common cases (get by id,
list with pagination, create, soft-delete) — they call
`vendor_repository.get_by_id(vendor_id)`, not
`session.execute(select(Vendor).where(...))`.

Concrete repositories add only what's genuinely domain-specific
(`InvoiceRepository.list_by_vendor_and_status`,
`VendorRepository.get_by_tax_id`) on top of this base.

WHY A CLASS AND NOT FREE FUNCTIONS
------------------------------------
Bundling the `AsyncSession` in `__init__` means services construct a
repository once per request/unit-of-work
(`InvoiceRepository(session)`) and every method call automatically
participates in the same transaction — no session threading through
every function call, and trivial to swap for a fake/in-memory
repository in unit tests.

SOFT DELETE
-----------
`get_by_id` and `list_all` filter out soft-deleted rows
(`deleted_at IS NULL`) by default for any model with `SoftDeleteMixin`,
via `_apply_not_deleted_filter`. Models without that mixin (e.g.
`GoodsReceiptLine`) simply skip the filter — checked via
`hasattr(self.model, "deleted_at")` rather than requiring every
repository to declare it explicitly.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def _base_select(self) -> Select:
        stmt = select(self.model)
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        return stmt

    async def get_by_id(self, id_: uuid.UUID) -> ModelT | None:
        stmt = self._base_select().where(self.model.id == id_)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, id_: uuid.UUID) -> ModelT | None:
        """Load one row with a database row lock for serialized mutations."""
        stmt = self._base_select().where(self.model.id == id_).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(self, id_: uuid.UUID) -> ModelT:
        instance = await self.get_by_id(id_)
        if instance is None:
            raise NotFoundError(
                f"{self.model.__name__} with id {id_} not found.",
                details={"model": self.model.__name__, "id": str(id_)},
            )
        return instance

    async def list_all(self, *, offset: int = 0, limit: int = 25) -> list[ModelT]:
        stmt = self._base_select().offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_all(self) -> int:
        stmt = select(func.count()).select_from(self._base_select().subquery())
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    async def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        await self.session.flush()  # populate server-generated fields (id, timestamps)
        return instance

    async def update(self, instance: ModelT, **fields: Any) -> ModelT:
        for key, value in fields.items():
            if value is not None:
                setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def soft_delete(self, instance: ModelT) -> None:
        if not hasattr(instance, "deleted_at"):
            raise TypeError(
                f"{type(instance).__name__} does not support soft delete "
                f"(no SoftDeleteMixin)."
            )
        from datetime import datetime, timezone

        instance.deleted_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        await self.session.flush()
