"""
app.agents.prompts.treasury_prompts
=======================================
One prompt, same kind as `fraud_detection_prompts`: the forecast and
its risk level are already fully determined by
`TreasuryService.forecast_cash_flow` and `assess_liquidity_risk` by the
time this runs. This prompt only turns the forecast's numbers and
event list into a readable paragraph — it does not compute, judge, or
second-guess the forecast.
"""

from __future__ import annotations

import json
from decimal import Decimal


def build_narrative_prompt(
    *,
    starting_balance: Decimal,
    ending_balance: Decimal,
    lowest_balance: Decimal,
    lowest_balance_date: str | None,
    horizon_days: int,
    events: list[dict],
) -> tuple[str, str]:
    system_prompt = """\
You are writing a one-paragraph summary of a cash flow forecast for a \
finance director. You are given a starting cash balance, a projected \
ending balance, the lowest point the balance is projected to reach (and \
when), and the list of dated inflow/outflow events driving the \
projection. These numbers have ALREADY been computed — do not \
recalculate, second-guess, or add events not in the list. Write a \
clear, concise paragraph a busy reader can scan in a few seconds, \
naming the specific event(s) that drive the lowest point if the \
balance dips notably. If there are no events, say plainly that no \
inflows or outflows are currently scheduled in this window.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"narrative": "<one paragraph, plain text, no markdown>"}
"""
    payload = {
        "starting_balance": str(starting_balance),
        "ending_balance": str(ending_balance),
        "lowest_balance": str(lowest_balance),
        "lowest_balance_date": lowest_balance_date,
        "horizon_days": horizon_days,
        "events": events,
    }
    user_prompt = (
        "Here is the forecast as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Write the summary paragraph as instructed."
    )
    return system_prompt, user_prompt
