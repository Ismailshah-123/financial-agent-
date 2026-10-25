"""
app.agents.prompts.bank_reconciliation_prompts
===================================================
Two prompts `BankReconciliationAgent` needs — both for situations the
deterministic matcher in `BankReconciliationService` deliberately
leaves unresolved (see that service's module docstring):

1. **Disambiguation** — multiple same-amount payments in the date
   window; which one does the statement line's description text most
   plausibly refer to?
2. **Unrecognized transaction classification** — zero candidates at
   all; what KIND of transaction does the description suggest (bank
   fee, interest, unknown), so a human reviewing it has a head start
   instead of a blank description string.

Same conventions as every other prompts module in this codebase:
strict JSON, honest "unclear"/"uncertain" options rather than a forced
guess, confidence-gated by the agent.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

DISAMBIGUATE_MATCH_SYSTEM_PROMPT = """\
You are helping reconcile a bank statement against a company's internal \
payment records. A bank statement line needs to be matched to ONE of \
several candidate payments that all share the same amount and fall \
within a plausible date range. Use the statement line's description \
text and each candidate's date to judge which candidate is the more \
plausible match. If the description gives no useful signal to \
distinguish between them, say so honestly rather than guessing — picking \
the wrong one misattributes a real payment.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"selected_candidate_index": <int, 0-based index into the candidate \
list, or null if genuinely unclear>, "confidence": <0.0-1.0>, \
"reasoning": "<1-2 sentence explanation>"}
"""


def build_disambiguate_match_prompt(
    *,
    statement_description: str,
    statement_amount: Decimal,
    statement_date: date,
    candidates: list[dict],
) -> tuple[str, str]:
    payload = {
        "statement_line": {
            "description": statement_description,
            "amount": str(statement_amount),
            "date": statement_date.isoformat(),
        },
        "candidates": candidates,
    }
    user_prompt = (
        "Here is the statement line and its candidates as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Select the best matching candidate as instructed."
    )
    return DISAMBIGUATE_MATCH_SYSTEM_PROMPT, user_prompt


CLASSIFY_UNMATCHED_SYSTEM_PROMPT = """\
You are helping reconcile a bank statement. A statement line has NO \
corresponding internal payment record at all — it may be a bank fee, \
interest earned, a bank error, or something else entirely. Based only \
on the description text and amount sign (negative = money left the \
account, positive = money entered it), suggest the most likely \
category. If the description is too generic or unfamiliar to judge, \
say so honestly.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"category": "<bank_fee|interest|bank_error|unknown>", "confidence": \
<0.0-1.0>, "reasoning": "<1-2 sentence explanation>"}
"""


def build_classify_unmatched_prompt(
    *, statement_description: str, statement_amount: Decimal
) -> tuple[str, str]:
    payload = {"description": statement_description, "amount": str(statement_amount)}
    user_prompt = (
        "Here is the unmatched statement line as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Classify it as instructed."
    )
    return CLASSIFY_UNMATCHED_SYSTEM_PROMPT, user_prompt
