"""
app.agents.accounts_receivable
=================================
The Accounts Receivable agent: assesses collection risk (how overdue is
this invoice, what should happen next) and credit-limit exposure (is
this customer's total outstanding balance approaching or over their
configured limit). See `agent.py` for the full workflow — it follows
the same pattern as `app.agents.accounts_payable.agent`, the reference
implementation.
"""

from app.agents.accounts_receivable.agent import AccountsReceivableAgent

__all__ = ["AccountsReceivableAgent"]
