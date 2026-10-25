"""
app.agents.fraud_detection
=============================
The Fraud Detection agent: given one OutgoingPayment, screens it and
its Vendor against deterministic fraud signals and reports the result.
See `agent.py` for the full workflow and
`app.services.fraud_detection_service` for the rule-based signal
detection this agent is built on top of.
"""

from app.agents.fraud_detection.agent import FraudDetectionAgent

__all__ = ["FraudDetectionAgent"]
