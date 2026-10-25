"""
app.agents.accounts_payable
=============================
The Accounts Payable agent: the reference implementation every other
agent (AR, Tax, Treasury, ...) follows. See `agent.py` for the full
workflow (duplicate check -> 3-way match -> LLM narrative -> AgentDecision).
"""

from app.agents.accounts_payable.agent import AccountsPayableAgent

__all__ = ["AccountsPayableAgent"]
