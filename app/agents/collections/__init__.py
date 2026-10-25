"""
app.agents.collections
==========================
The Collections agent: portfolio- and customer-level AR aging and
collection-priority assessment — the aggregate view on top of what
`AccountsReceivableAgent` already does per invoice (see agent.py's
module docstring for exactly where the boundary between the two sits).
"""

from app.agents.collections.agent import CollectionsAgent

__all__ = ["CollectionsAgent"]
