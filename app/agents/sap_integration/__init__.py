"""
app.agents.sap_integration
=============================
The SAP Integration agent: syncs Vendor/Customer master data to SAP
Business One and reasons about the outcome — a clean create is LOW risk
and self-resolves, but a field-level conflict (local record and SAP
disagree) or a sync failure (SAP rejected the request) becomes an
`AgentDecision` requiring human review rather than being silently
resolved either direction. See `agent.py`.

*** See `app.integrations.sap.client`'s module docstring: the SAP HTTP
client this agent depends on has not been exercised against a real SAP
B1 Service Layer instance. Verify against a real sandbox before
production use. ***
"""

from app.agents.sap_integration.agent import SAPIntegrationAgent

__all__ = ["SAPIntegrationAgent"]
