"""
app.agents.prompts.accounts_receivable_prompts
==================================================
Prompt template for the AR Agent's LLM-assisted reasoning — narrow and
well-defined, same philosophy as
`app.agents.prompts.accounts_payable_prompts`: the actual risk
arithmetic (days overdue, credit-limit comparison) is computed
deterministically by the agent before this prompt ever runs; the LLM's
job is only to turn that into a clear explanation and flag qualitative
context a pure number can't capture (e.g. a customer who's slightly
over their limit but has an otherwise flawless payment history vs. one
who's chronically late).
"""

from __future__ import annotations

import json
from decimal import Decimal

from app.db.models.ar_invoice import ARInvoice
from app.db.models.customer import Customer

COLLECTION_RISK_SYSTEM_PROMPT = """\
You are a financial reasoning assistant supporting an Accounts \
Receivable collections and credit-risk workflow at an enterprise \
finance department. You are given deterministic facts about a \
customer's outstanding balance, credit limit, and how overdue a \
specific invoice is — this arithmetic has already been computed \
correctly and you must treat it as ground truth. Your job is to:

1. Explain the situation in clear, professional language a collections \
analyst or credit manager can read in a few seconds.
2. Recommend a concrete next action appropriate to the severity (e.g. \
"send a friendly payment reminder", "escalate to a formal collections \
call", "place new orders on hold pending payment") — recommend, do not \
assume authority to act.
3. Note any additional qualitative concern visible in the data (e.g. a \
pattern across multiple overdue invoices, if provided) that the raw \
numbers alone might not convey.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"narrative": "<2-4 sentence explanation>", "recommended_action": \
"<one short phrase>", "additional_concern": "<short note, or empty \
string if none>"}
"""


def build_collection_risk_prompt(
    *,
    invoice: ARInvoice,
    customer: Customer,
    days_overdue: int,
    customer_total_outstanding: Decimal,
) -> tuple[str, str]:
    payload = {
        "customer_name": customer.name,
        "customer_credit_limit": str(customer.credit_limit) if customer.credit_limit else None,
        "customer_total_outstanding": str(customer_total_outstanding),
        "invoice_number": invoice.invoice_number,
        "invoice_total": str(invoice.total_amount),
        "invoice_amount_outstanding": str(invoice.amount_outstanding),
        "invoice_due_date": invoice.due_date.isoformat(),
        "days_overdue": days_overdue,
    }
    user_prompt = (
        "Here is the AR collection/credit-risk data as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Produce the narrative, recommended action, and any additional "
        "concern as instructed."
    )
    return COLLECTION_RISK_SYSTEM_PROMPT, user_prompt
