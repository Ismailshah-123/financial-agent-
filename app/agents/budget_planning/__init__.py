"""
app.agents.budget_planning
==============================
The Budget Planning agent: given one Budget, computes its pace-adjusted
variance against actual account activity and reports the risk of
breaching it. See `agent.py` for the full workflow and
`app.services.budget_service` for the deterministic variance
calculation this agent is built on top of.
"""

from app.agents.budget_planning.agent import BudgetPlanningAgent

__all__ = ["BudgetPlanningAgent"]
