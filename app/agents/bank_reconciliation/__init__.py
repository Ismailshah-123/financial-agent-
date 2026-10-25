"""
app.agents.bank_reconciliation
=================================
The Bank Reconciliation agent: given one BankStatementLine, recommends
how to resolve it (confirm a match, flag a discrepancy, or classify an
unrecognized transaction). See `agent.py` for the full workflow and
`app.services.bank_reconciliation_service` for the deterministic
matching it builds on.
"""

from app.agents.bank_reconciliation.agent import BankReconciliationAgent

__all__ = ["BankReconciliationAgent"]
