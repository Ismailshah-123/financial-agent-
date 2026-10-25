"""
app.agents.prompts.fraud_detection_prompts
==============================================
One prompt, and it's different in kind from every other prompts module
in this codebase: it does NOT ask the LLM to classify, decide, or judge
anything. `FraudDetectionService.detect_signals` has already produced
the complete, deterministic list of findings and their severities by
the time this prompt runs — see that service's module docstring for
why fraud risk-leveling specifically should never depend on an LLM
call succeeding. This prompt's only job is turning that structured
signal list into one readable paragraph a human can scan quickly,
instead of a bullet list of raw signal descriptions. If the LLM call
fails, `FraudDetectionAgent` falls back to literally concatenating the
signal descriptions — less pleasant to read, but exactly as accurate,
since no judgment was ever delegated to the LLM in the first place.
"""

from __future__ import annotations

import json
from decimal import Decimal


def build_narrative_prompt(
    *,
    vendor_name: str,
    payment_amount: Decimal,
    signals: list[dict],
) -> tuple[str, str]:
    system_prompt = """\
You are writing a one-paragraph summary of a payment fraud screening \
result for a finance director to read before approving a payment. You \
are given a vendor name, payment amount, and a list of findings that \
have ALREADY been determined — do not add, remove, reinterpret, or \
second-guess any finding, and do not invent a conclusion about whether \
this is or isn't fraud. Simply synthesize the given findings into a \
clear, concise paragraph a busy reader can scan in a few seconds. If \
the findings list is empty, say plainly that no fraud signals were \
found.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"narrative": "<one paragraph, plain text, no markdown>"}
"""
    payload = {
        "vendor_name": vendor_name,
        "payment_amount": str(payment_amount),
        "findings": signals,
    }
    user_prompt = (
        "Here is the screening result as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Write the summary paragraph as instructed."
    )
    return system_prompt, user_prompt
