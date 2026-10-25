"""
Unit tests for app.agents.base_agent.BaseAgent — verifies the run()
wrapper's guarantees: permission gating, exception containment (a
subclass's exception must never propagate out of run()), and that
decisions requiring approval flip the result status to
AWAITING_APPROVAL.
"""

from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.agents.schemas import (
    AgentContext,
    AgentDecision,
    AgentExecutionStatus,
    ConfidenceMethod,
    ConfidenceScore,
    RollbackStrategy,
)
from app.core.constants import AgentType, Permission, RiskLevel, UserRole


class _FakeSession:
    """Minimal stand-in for AsyncSession — just enough for
    BaseRepository.add() (sync .add(), async .flush()) to succeed
    without a real database. BaseAgent's constructor now requires a
    session (see app.services.approval_service.ApprovalService, wired
    in so every agent persists a real ApprovalRequestRecord for
    requires_approval=True decisions, not just a transient event) —
    these tests only exercise run()'s control flow, never touch real
    persistence, so a fake is the right tool here, same pattern as
    tests/unit/test_posting_service.py's _FakeSession."""

    def add(self, instance) -> None:
        pass

    async def flush(self) -> None:
        pass


def _context() -> AgentContext:
    return AgentContext(
        correlation_id="test-correlation-id",
        tenant_id="tenant-1",
        actor_id="user-1",
        actor_role=UserRole.ACCOUNTANT.value,
    )


class _AlwaysSucceedsAgent(BaseAgent):
    agent_type = AgentType.ACCOUNTS_PAYABLE

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        return [
            AgentDecision(
                agent_type=self.agent_type,
                summary="No action needed",
                reasoning="Invoice already matched in a prior run.",
                confidence=ConfidenceScore(
                    value=1.0,
                    method=ConfidenceMethod.RULE_BASED,
                    explanation="deduplicated",
                ),
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                rollback_strategy=RollbackStrategy(
                    is_reversible=True, compensating_action="none"
                ),
            )
        ]


class _RequiresApprovalAgent(BaseAgent):
    agent_type = AgentType.ACCOUNTS_PAYABLE

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        return [
            AgentDecision(
                agent_type=self.agent_type,
                summary="Pay vendor invoice",
                reasoning="3-way match succeeded.",
                confidence=ConfidenceScore(
                    value=0.95,
                    method=ConfidenceMethod.RULE_BASED,
                    explanation="PO, GRPO, and invoice amounts match exactly",
                ),
                risk_level=RiskLevel.HIGH,
                requires_approval=False,  # deliberately wrong — schema must fix it
                rollback_strategy=RollbackStrategy(
                    is_reversible=True, compensating_action="void_journal_entry"
                ),
            )
        ]


class _AlwaysFailsAgent(BaseAgent):
    agent_type = AgentType.ACCOUNTS_PAYABLE

    async def _execute(self, context: AgentContext) -> list[AgentDecision]:
        raise RuntimeError("simulated downstream failure")


async def test_successful_run_returns_success_status() -> None:
    agent = _AlwaysSucceedsAgent(_FakeSession())  # type: ignore[arg-type]
    result = await agent.run(_context(), actor_role=UserRole.ACCOUNTANT)
    assert result.status == AgentExecutionStatus.SUCCESS
    assert len(result.decisions) == 1


async def test_high_risk_decision_flips_status_to_awaiting_approval() -> None:
    agent = _RequiresApprovalAgent(_FakeSession())  # type: ignore[arg-type]
    result = await agent.run(_context(), actor_role=UserRole.ACCOUNTANT)
    assert result.status == AgentExecutionStatus.AWAITING_APPROVAL
    assert result.decisions[0].requires_approval is True


async def test_exception_in_execute_is_contained_and_returns_failed_status() -> None:
    agent = _AlwaysFailsAgent(_FakeSession())  # type: ignore[arg-type]
    result = await agent.run(_context(), actor_role=UserRole.ACCOUNTANT)
    assert result.status == AgentExecutionStatus.FAILED
    assert "simulated downstream failure" in (result.error_message or "")


async def test_unauthorized_role_never_executes_agent() -> None:
    agent = _AlwaysSucceedsAgent(_FakeSession())  # type: ignore[arg-type]
    agent.required_permission = Permission.ADMIN_USER_MANAGE  # role won't have this
    result = await agent.run(_context(), actor_role=UserRole.VIEWER)
    assert result.status == AgentExecutionStatus.FAILED
    assert "not permitted" in (result.error_message or "")
