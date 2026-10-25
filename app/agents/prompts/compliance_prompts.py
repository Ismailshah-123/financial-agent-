"""
app.agents.prompts.compliance_prompts
=========================================
One prompt, same kind as every other rule-based agent's narrative
prompt this session: the remittance assessment and risk level are
already fully computed by `app.services.fbr_compliance_service` by the
time this runs. This prompt only narrates the already-decided numbers
into prose.
"""

from __future__ import annotations

import json
from decimal import Decimal


def build_narrative_prompt(
    *,
    period_start: str,
    period_end: str,
    liability_incurred: Decimal,
    amount_remitted: Decimal,
    outstanding_amount: Decimal,
    days_since_period_end: int,
) -> tuple[str, str]:
    system_prompt = """\
You are writing a one-paragraph summary of an FBR withholding-tax \
remittance compliance check for a finance director. You are given the \
period checked, the withholding tax liability incurred in that period, \
how much has been remitted to FBR against it, the outstanding amount, \
and how many days have passed since the period ended. These numbers \
have ALREADY been computed — do not recalculate or second-guess them, \
and do not state a specific legal filing deadline as fact (the exact \
FBR deadline is not verified-current in this system — refer to it only \
as "the applicable FBR deadline" if you need to, not a specific number \
of days). Write a clear, concise paragraph a busy reader can scan in a \
few seconds.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"narrative": "<one paragraph, plain text, no markdown>"}
"""
    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "liability_incurred": str(liability_incurred),
        "amount_remitted": str(amount_remitted),
        "outstanding_amount": str(outstanding_amount),
        "days_since_period_end": days_since_period_end,
    }
    user_prompt = (
        "Here is the remittance assessment as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Write the summary paragraph as instructed."
    )
    return system_prompt, user_prompt
