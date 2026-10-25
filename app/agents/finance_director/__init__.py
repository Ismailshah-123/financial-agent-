"""
app.agents.finance_director
===============================
The Finance Director agent: orchestrates a period review across
TreasuryAgent, ComplianceAgent, and BudgetPlanningAgent (run once per
budget overlapping the period), synthesizing their findings into one
executive-level decision. See `agent.py` for the full orchestration
design and its deliberate v1 boundaries.
"""

from app.agents.finance_director.agent import FinanceDirectorAgent

__all__ = ["FinanceDirectorAgent"]
