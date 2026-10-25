"""
app.agents.treasury
=======================
The Treasury agent: produces a cash flow forecast and liquidity risk
assessment over a forecast window (not tied to a single entity, unlike
every other agent in this platform — see agent.py's module docstring).
"""

from app.agents.treasury.agent import TreasuryAgent

__all__ = ["TreasuryAgent"]
