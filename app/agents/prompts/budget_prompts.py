"""
app.agents.prompts.budget_prompts
=====================================
One prompt, same kind as `treasury_prompts`/`fraud_detection_prompts`:
the variance and risk level are already fully computed by
`app.services.budget_service` by the time this runs. This prompt only
narrates the already-decided numbers into prose.
"""

from __future__ import annotations

import json
from decimal import Decimal


def build_narrative_prompt(
    *,
    budget_name: str,
    account_code: str,
    account_type: str,
    budgeted_amount: Decimal,
    actual_amount: Decimal,
    elapsed_fraction: Decimal,
    expected_amount_at_pace: Decimal,
    variance_ratio: Decimal,
) -> tuple[str, str]:
    system_prompt = """\
You are writing a one-paragraph summary of a budget-vs-actual variance \
check for a finance director. You are given a budget's target amount, \
the actual amount recorded so far, how far through the budget period \
things are, and a variance ratio (positive means trending unfavorably — \
overspending for an expense budget, or underearning for a revenue \
budget; negative or zero means on track or better). These numbers have \
ALREADY been computed — do not recalculate or second-guess them. Write \
a clear, concise paragraph a busy reader can scan in a few seconds. If \
the elapsed fraction is low (early in the period), note that the \
finding is still an early signal, not a conclusion — a budget can look \
off-pace early on due to one-time or front-loaded costs.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"narrative": "<one paragraph, plain text, no markdown>"}
"""
    payload = {
        "budget_name": budget_name,
        "account_code": account_code,
        "account_type": account_type,
        "budgeted_amount": str(budgeted_amount),
        "actual_amount": str(actual_amount),
        "elapsed_fraction": str(elapsed_fraction),
        "expected_amount_at_pace": str(expected_amount_at_pace),
        "variance_ratio": str(variance_ratio),
    }
    user_prompt = (
        "Here is the variance check as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Write the summary paragraph as instructed."
    )
    return system_prompt, user_prompt
