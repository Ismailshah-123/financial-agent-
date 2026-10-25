"""
app.agents.prompts.sap_integration_prompts
=============================================
Prompt templates for the two situations where the SAP Integration agent
benefits from an LLM: explaining a field-level conflict between a local
record and what SAP currently has (so a human can decide which side is
correct), and translating a raw SAP error message into something a
non-SAP-specialist can act on. Same philosophy as every other agent's
prompts in this codebase: the LLM explains, it does not decide — the
agent's own risk assessment (not the LLM) determines whether the run
requires approval.
"""

from __future__ import annotations

import json
from typing import Any

CONFLICT_SYSTEM_PROMPT = """\
You are a financial systems integration assistant. A record in this \
platform and its counterpart in SAP Business One have diverging field \
values — you are given exactly which fields differ and the value on \
each side. Do not guess at which side is "correct"; you do not have \
enough context to know whether the local system or SAP was updated \
more recently or by someone with more authority. Your job is to:

1. Summarize the conflict clearly for a human integration analyst.
2. Suggest what KIND of investigation would resolve it (e.g. "check \
which system was edited most recently", "confirm with the vendor \
directly if this is a legitimate contact change") — never assert a \
specific resolution.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"narrative": "<2-4 sentence summary of the conflict>", \
"suggested_investigation": "<one short phrase>"}
"""

SYNC_FAILURE_SYSTEM_PROMPT = """\
You are a financial systems integration assistant. A sync attempt to \
SAP Business One failed with a raw error code and message from SAP's \
API. Translate this into a plain-language explanation a finance ops \
person (not a SAP technical specialist) can understand, and suggest \
what to check first — without inventing specifics about the customer's \
SAP configuration you cannot know.

Respond with ONLY a JSON object, no other text, matching exactly this \
schema:
{"narrative": "<2-3 sentence plain-language explanation>", \
"suggested_first_check": "<one short phrase>"}
"""


def build_conflict_narrative_prompt(
    *, entity_type: str, entity_id: str, conflicting_fields: dict[str, tuple[Any, Any]]
) -> tuple[str, str]:
    payload = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "conflicts": {
            field_name: {"local_value": str(local_val), "sap_value": str(sap_val)}
            for field_name, (local_val, sap_val) in conflicting_fields.items()
        },
    }
    user_prompt = (
        "Here is the sync conflict as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Produce the narrative and suggested investigation as instructed."
    )
    return CONFLICT_SYSTEM_PROMPT, user_prompt


def build_sync_failure_narrative_prompt(
    *, entity_type: str, entity_id: str, error_message: str
) -> tuple[str, str]:
    payload = {"entity_type": entity_type, "entity_id": entity_id, "sap_error": error_message}
    user_prompt = (
        "Here is the sync failure as JSON:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Produce the narrative and suggested first check as instructed."
    )
    return SYNC_FAILURE_SYSTEM_PROMPT, user_prompt
