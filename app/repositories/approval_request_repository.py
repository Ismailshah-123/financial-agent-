"""
app.repositories.approval_request_repository
=================================================
`ApprovalRequestRecord` data access. `list_pending` is the query an
"approval inbox" is built on.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, select

from app.db.models.approval_request import ApprovalRequestRecord
from app.repositories.base_repository import BaseRepository
from app.services.approval_views import (
    APPROVED,
    EXECUTED,
    EXECUTING,
    EXECUTION_PENDING,
    FAILED,
    OLDEST_FIRST_VIEWS,
    PENDING,
    REJECTED,
    summarize_approval_counts,
)


class ApprovalRequestRepository(BaseRepository[ApprovalRequestRecord]):
    model = ApprovalRequestRecord

    async def list_pending(
        self, *, agent_type: str | None = None, offset: int = 0, limit: int = 25
    ) -> list[ApprovalRequestRecord]:
        stmt = self._base_select().where(ApprovalRequestRecord.status == "pending")
        if agent_type is not None:
            stmt = stmt.where(ApprovalRequestRecord.agent_type == agent_type)
        stmt = stmt.order_by(ApprovalRequestRecord.created_at.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_pending(self, *, agent_type: str | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(ApprovalRequestRecord)
            .where(ApprovalRequestRecord.status == PENDING)
        )
        if agent_type is not None:
            stmt = stmt.where(ApprovalRequestRecord.agent_type == agent_type)
        return int((await self.session.execute(stmt)).scalar_one())

    @staticmethod
    def _view_conditions(view: str) -> list[ColumnElement[bool]]:
        """SQL predicates for a named inbox view (see app.services.approval_views)."""
        model = ApprovalRequestRecord
        executable = model.action_type.is_not(None)
        if view == "pending":
            return [model.status == PENDING]
        if view == "approved":
            return [model.status == APPROVED]
        if view == "rejected":
            return [model.status == REJECTED]
        if view == "awaiting_execution":
            return [
                model.status == APPROVED,
                executable,
                model.execution_status == EXECUTION_PENDING,
            ]
        if view == "executing":
            return [model.status == APPROVED, executable, model.execution_status == EXECUTING]
        if view == "failed":
            return [model.status == APPROVED, executable, model.execution_status == FAILED]
        if view == "executed":
            return [model.status == APPROVED, executable, model.execution_status == EXECUTED]
        return []  # "all"

    async def list_view(
        self,
        *,
        view: str = "pending",
        agent_type: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> list[ApprovalRequestRecord]:
        stmt = self._base_select()
        for condition in self._view_conditions(view):
            stmt = stmt.where(condition)
        if agent_type is not None:
            stmt = stmt.where(ApprovalRequestRecord.agent_type == agent_type)
        if view in OLDEST_FIRST_VIEWS:
            stmt = stmt.order_by(
                ApprovalRequestRecord.created_at.asc(), ApprovalRequestRecord.id.asc()
            )
        else:
            stmt = stmt.order_by(
                ApprovalRequestRecord.created_at.desc(), ApprovalRequestRecord.id.desc()
            )
        result = await self.session.execute(stmt.offset(offset).limit(limit))
        return list(result.scalars().all())

    async def summary_counts(self) -> dict[str, int]:
        model = ApprovalRequestRecord
        stmt = select(
            model.status,
            model.execution_status,
            model.action_type.is_not(None),
            func.count(),
        ).group_by(model.status, model.execution_status, model.action_type.is_not(None))
        rows = (await self.session.execute(stmt)).all()
        return summarize_approval_counts(
            (str(r[0]), str(r[1]), bool(r[2]), int(r[3])) for r in rows
        )


    async def get_by_id_for_update(self, id_):
        stmt = self._base_select().where(ApprovalRequestRecord.id == id_).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
