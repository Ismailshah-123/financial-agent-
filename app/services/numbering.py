"""
app.services.numbering
========================
Human-readable document number generation (invoice-facing PO numbers,
GRPO numbers, payment numbers, journal entry numbers) — separate from
the internal UUID primary key.

WHY NOT JUST AN AUTO-INCREMENT COLUMN
----------------------------------------
Auto-increment sequences don't survive a multi-tenant / SAP-synced world
cleanly (two tenants both minting `PO-000001` is fine as long as the
prefix and tenant scope are part of the identity, which this format
provides), and they leak business volume information (a competitor
watching invoice numbers can estimate order volume) unless obfuscated.
This generator produces a sortable, collision-resistant, per-type
prefixed number without needing a database sequence per document type.

Production hardening note: today this uses a UUID4 suffix, which is
collision-resistant but not strictly sequential. If a customer's
business process requires *strictly sequential, gap-free* numbering
(common in some tax jurisdictions for invoices), swap the suffix
generation for a Postgres sequence per `(tenant_id, document_type)` —
the function signature here is intentionally the seam for that change.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def generate_document_number(prefix: str) -> str:
    """e.g. generate_document_number('PO') -> 'PO-20260811-9F3A1C2B'"""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:8].upper()
    return f"{prefix}-{date_part}-{suffix}"
