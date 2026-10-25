"""
app.agents.tax
=================
The Tax agent: given an AP invoice, (1) sanity-checks its recorded
sales-tax amount against currently active tax codes and (2) recommends
which Section 153 withholding-tax code should apply when it's paid.
See `agent.py` for the full workflow and — importantly — its module
docstring's note on what this agent deliberately does NOT attempt to
verify, and why.
"""

from app.agents.tax.agent import TaxAgent

__all__ = ["TaxAgent"]
