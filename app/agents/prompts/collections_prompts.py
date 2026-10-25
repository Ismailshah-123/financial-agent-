"""
app.agents.prompts.collections_prompts
==========================================
Same discipline as `treasury_prompts`/`fraud_detection_prompts`: the
priority tier, score, and reasons are already fully determined by
`app.services.aging_calculations.score_collection_priority` by the
time this runs. This prompt turns those already-computed facts into a
plain-language explanation and a draft customer-facing follow-up
message — it does not compute, judge, or override the tier, the score,
or the deterministic `recommended_action` (which stays a separate,
fixed field the caller already has; the LLM narrates it, it doesn't
invent a competing one). See `CollectionsAgent._synthesize_assessment`
for the graceful-degradation fallback when every LLM provider fails or
none is configured.
"""

from __future__ import annotations

import json
from decimal import Decimal


def build_collection_assessment_prompt(
    *,
    customer_name: str,
    priority_tier: str,
    priority_score: int,
    priority_reasons: list[str],
    recommended_action: str,
    total_outstanding: Decimal,
    currency: str,
    oldest_days_overdue: int,
    bucket_totals: dict[str, Decimal],
    credit_limit: Decimal | None,
    credit_utilization: Decimal | None,
    open_invoice_count: int,
    overdue_invoice_count: int,
) -> tuple[str, str]:
    system_prompt = """\
You are writing a short collections assessment for a finance manager \
about one customer's accounts receivable position. You are given the \
customer's aging totals, an ALREADY-COMPUTED collection priority tier \
and score, the deterministic reasons behind that score, and an \
ALREADY-DECIDED recommended action. Do not recalculate, second-guess, \
re-rank, or contradict any of these — treat every number and the tier \
as ground truth. Do not invent facts, invoices, or payment history not \
given to you.

Produce two things:
1. A short plain-language explanation (2-4 sentences) a finance manager \
   can read in a few seconds, covering why this customer has this \
   priority tier, referencing the given reasons.
2. A short draft follow-up message (3-6 sentences) that could be sent \
   to the customer, in a tone appropriate to the tier: a friendly \
   reminder for "low"/"medium", a firmer notice for "high", and a \
   formal final-notice tone for "critical". Never threaten legal action \
   yourself even at "critical" — say a formal review is underway and a \
   representative will follow up, since only a human decides that step.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"narrative": "<plain text, no markdown>", "draft_followup_message": "<plain text, no markdown>"}
"""
    payload = {
        "customer_name": customer_name,
        "priority_tier": priority_tier,
        "priority_score": priority_score,
        "priority_reasons": priority_reasons,
        "recommended_action": recommended_action,
        "total_outstanding": str(total_outstanding),
        "currency": currency,
        "oldest_days_overdue": oldest_days_overdue,
        "bucket_totals": {k: str(v) for k, v in bucket_totals.items()},
        "credit_limit": str(credit_limit) if credit_limit is not None else None,
        "credit_utilization": (
            f"{float(credit_utilization):.2%}" if credit_utilization is not None else None
        ),
        "open_invoice_count": open_invoice_count,
        "overdue_invoice_count": overdue_invoice_count,
    }
    user_prompt = (
        "Here is the customer's aging position as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Write the explanation and draft follow-up message as instructed."
    )
    return system_prompt, user_prompt
