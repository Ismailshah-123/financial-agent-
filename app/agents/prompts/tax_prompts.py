"""
app.agents.prompts.tax_prompts
=================================
One prompt: classify an invoice's line items as predominantly GOODS or
SERVICES. This is the one part of withholding-tax recommendation that
isn't already deterministic — `TaxAgent` needs it to pick which of the
four seeded Section 153 codes to recommend (goods/services x
filer/non-filer; see `alembic/versions/0005_tax_codes.py`), and neither
`Invoice` nor `InvoiceLine` captures a goods-vs-services flag today.

Like `accounts_payable_prompts`, this demands strict JSON so
`TaxAgent._parse_llm_json` can parse it deterministically, and the
prompt explicitly permits an honest "ambiguous" answer rather than
forcing a guess — `TaxAgent` treats anything below its confidence bar
as "needs manual categorization" instead of silently picking a side,
since guessing wrong here picks the wrong withholding rate.
"""

from __future__ import annotations

import json

from app.db.models.invoice import Invoice
from app.db.models.vendor import Vendor

TAX_CATEGORY_SYSTEM_PROMPT = """\
You are a tax classification assistant supporting a Pakistan withholding-tax \
(Section 153, Income Tax Ordinance 2001) recommendation. Given an invoice's \
line item descriptions, classify the invoice as predominantly a supply of \
GOODS or a supply of SERVICES — the two categories are subject to different \
withholding rates. If the invoice mixes both, classify by the larger share \
of the total line value. Only report high confidence if the descriptions \
clearly indicate one category; if the descriptions are genuinely ambiguous \
or too vague to tell, say so honestly rather than guessing — an incorrect \
category picks the wrong withholding rate.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"category": "<goods|services|ambiguous>", "confidence": <0.0-1.0>, \
"reasoning": "<1-2 sentence explanation>"}
"""


def build_tax_category_prompt(*, invoice: Invoice, vendor: Vendor) -> tuple[str, str]:
    payload = {
        "vendor_name": vendor.name,
        "invoice_number": invoice.invoice_number,
        "line_items": [
            {"description": line.description, "quantity": str(line.quantity)}
            for line in invoice.lines
        ],
    }
    user_prompt = (
        "Here is the invoice's line item data as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Classify it as instructed."
    )
    return TAX_CATEGORY_SYSTEM_PROMPT, user_prompt
