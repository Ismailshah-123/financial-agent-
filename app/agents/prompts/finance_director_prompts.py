"""
app.agents.prompts.finance_director_prompts
================================================
Different in kind from every other prompts module this session: those
narrate ONE already-computed finding. This one synthesizes MULTIPLE
already-computed findings (a cash flow forecast, an FBR compliance
check, a set of budget variance checks) from
`app.agents.finance_director.agent` into one executive-level paragraph.
Still the same underlying rule: every number and every risk level
handed to this prompt has already been decided by the sub-agents'
deterministic logic — this prompt's only job is composing them into a
coherent summary, not judging any of them itself.
"""

from __future__ import annotations

import json


def build_synthesis_prompt(
    *,
    period_start: str,
    period_end: str,
    treasury_summary: str | None,
    treasury_risk: str | None,
    compliance_summary: str | None,
    compliance_risk: str | None,
    budget_summaries: list[dict],
    overall_risk: str,
) -> tuple[str, str]:
    system_prompt = """\
You are a Finance Director's AI assistant writing a one-paragraph \
executive summary of a period review. You are given three already- \
completed checks: a cash flow forecast, an FBR withholding remittance \
compliance check, and a set of budget variance checks — each with its \
own risk level and finding, already decided. A check may be missing \
(shown as null) if it could not run; mention that plainly rather than \
guessing why. Do not recalculate, re-judge, or contradict any finding \
— synthesize them into a clear paragraph a busy executive can read in \
a few seconds, leading with whatever is most urgent (highest risk) \
across the three checks.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"narrative": "<one paragraph, plain text, no markdown>"}
"""
    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "treasury": {"summary": treasury_summary, "risk": treasury_risk},
        "compliance": {"summary": compliance_summary, "risk": compliance_risk},
        "budgets": budget_summaries,
        "overall_risk": overall_risk,
    }
    user_prompt = (
        "Here is the period review as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Write the executive summary paragraph as instructed."
    )
    return system_prompt, user_prompt
