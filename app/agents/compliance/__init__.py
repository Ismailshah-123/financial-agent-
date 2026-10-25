"""
app.agents.compliance
=========================
The Compliance agent: FBR withholding-tax remittance compliance over a
period. See `agent.py` for the full workflow, scope boundaries (why
this isn't a general ledger/audit-integrity agent), and
`app.services.fbr_compliance_service` for the deterministic assessment
this agent is built on top of.
"""

from app.agents.compliance.agent import ComplianceAgent

__all__ = ["ComplianceAgent"]
