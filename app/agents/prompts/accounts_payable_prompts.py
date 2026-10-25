"""
app.agents.prompts.accounts_payable_prompts
==============================================
Prompt templates for the parts of AP reasoning that genuinely benefit
from an LLM — NOT for the matching arithmetic itself (that's
`app.services.matching_service.InvoiceMatchingEngine`, deterministic and
LLM-free by design). The LLM's job here is narrow and well-defined:

    1. `build_match_narrative_prompt` — turn a `MatchOutcome` (already
       computed) into a clear, human-readable explanation for the
       approver, and flag any subtle red flag the deterministic engine
       wouldn't catch (e.g. a vendor name that's suspiciously similar
       to but not exactly a known vendor — classic invoice-fraud pattern).
    2. `build_duplicate_narrative_prompt` — explain, in plain language,
       why a candidate duplicate invoice was flagged.

Both prompts demand strict JSON output with a fixed schema so the agent
can parse the response deterministically (`json.loads`) rather than
scraping free text — see `AccountsPayableAgent._parse_llm_json` for the
parse side of this contract.
"""

from __future__ import annotations

import json
from decimal import Decimal

from app.db.models.invoice import Invoice
from app.db.models.purchase_order import PurchaseOrder
from app.db.models.vendor import Vendor
from app.services.matching_service import MatchOutcome

MATCH_NARRATIVE_SYSTEM_PROMPT = """\
You are a financial reasoning assistant supporting an Accounts Payable \
approval workflow at an enterprise finance department. You are given the \
deterministic result of a purchase-order/goods-receipt/invoice matching \
check. Your job is NOT to redo the arithmetic — it has already been \
computed correctly and you must treat it as ground truth. Your job is to:

1. Explain the match result in clear, professional language a finance \
approver can read in a few seconds.
2. Independently flag any additional concern visible in the data that \
the matching engine would not catch — for example a vendor name that \
looks unusual, an invoice date far in the future or far in the past \
relative to the PO, or a due date that gives an unusually short payment \
window. Only flag genuine concerns; do not invent problems.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"narrative": "<2-4 sentence explanation>", "additional_risk_flagged": \
<true|false>, "additional_risk_reason": "<short reason, or empty string \
if additional_risk_flagged is false>"}
"""

DUPLICATE_NARRATIVE_SYSTEM_PROMPT = """\
You are a financial reasoning assistant supporting an Accounts Payable \
fraud-prevention check. You are given a newly submitted invoice and an \
existing invoice already on file that share the same vendor and invoice \
number. Explain, in plain language, why this pairing was flagged as a \
potential duplicate, and note any material differences between the two \
that might indicate this is NOT actually a duplicate (e.g. different \
amounts, which could mean a legitimate credit/debit note pair rather \
than a true duplicate submission).

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"narrative": "<2-3 sentence explanation>", "likely_true_duplicate": \
<true|false>}
"""


def build_match_narrative_prompt(
    *,
    invoice: Invoice,
    purchase_order: PurchaseOrder | None,
    vendor: Vendor,
    outcome: MatchOutcome,
) -> tuple[str, str]:
    payload = {
        "vendor_name": vendor.name,
        "invoice_number": invoice.invoice_number,
        "invoice_total": str(invoice.total_amount),
        "invoice_currency": invoice.currency,
        "invoice_date": invoice.invoice_date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "purchase_order_number": purchase_order.po_number if purchase_order else None,
        "po_order_date": purchase_order.order_date.isoformat() if purchase_order else None,
        "match_type": outcome.match_type.value,
        "is_matched": outcome.is_matched,
        "matched_line_count": outcome.matched_line_count,
        "total_line_count": outcome.total_line_count,
        "discrepancies": [
            {
                "invoice_line_number": d.invoice_line_number,
                "reason": d.reason,
                "expected": d.expected,
                "actual": d.actual,
            }
            for d in outcome.discrepancies
        ],
    }
    user_prompt = (
        "Here is the invoice matching data as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Produce the narrative and risk flag as instructed."
    )
    return MATCH_NARRATIVE_SYSTEM_PROMPT, user_prompt


def build_duplicate_narrative_prompt(
    *, new_invoice: Invoice, existing_invoice: Invoice, vendor: Vendor
) -> tuple[str, str]:
    payload = {
        "vendor_name": vendor.name,
        "new_invoice": {
            "invoice_number": new_invoice.invoice_number,
            "total_amount": str(new_invoice.total_amount),
            "invoice_date": new_invoice.invoice_date.isoformat(),
        },
        "existing_invoice": {
            "invoice_number": existing_invoice.invoice_number,
            "total_amount": str(existing_invoice.total_amount),
            "invoice_date": existing_invoice.invoice_date.isoformat(),
            "status": existing_invoice.status,
        },
    }
    user_prompt = (
        "Here is the potential duplicate invoice pairing as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Produce the narrative and duplicate assessment as instructed."
    )
    return DUPLICATE_NARRATIVE_SYSTEM_PROMPT, user_prompt
