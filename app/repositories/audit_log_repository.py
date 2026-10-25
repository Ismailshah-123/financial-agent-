from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AuditLog
from app.repositories.base_repository import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def list_logs(
        self,
        *,
        actor_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        outcome: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditLog], int]:
        stmt: Select = select(AuditLog)
        count_stmt = select(func.count()).select_from(AuditLog)
        filters = []
        if actor_id:
            filters.append(AuditLog.actor_id == actor_id)
        if action:
            filters.append(AuditLog.action == action)
        if resource_type:
            filters.append(AuditLog.resource_type == resource_type)
        if resource_id:
            filters.append(AuditLog.resource_id == resource_id)
        if outcome:
            filters.append(AuditLog.outcome == outcome)
        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)
        stmt = stmt.order_by(AuditLog.sequence_number.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        total_result = await self.session.execute(count_stmt)
        return list(result.scalars().all()), int(total_result.scalar_one())

    async def list_chain(self) -> list[AuditLog]:
        result = await self.session.execute(select(AuditLog).order_by(AuditLog.sequence_number.asc()))
        return list(result.scalars().all())
