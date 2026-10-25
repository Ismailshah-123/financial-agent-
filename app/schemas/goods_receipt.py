"""
app.schemas.goods_receipt
===========================
Request/response shapes for Goods Receipts (GRPO). A goods receipt is
always created against an existing Purchase Order's lines
(`purchase_order_line_id`), never freestanding — the service layer
validates that the referenced PO line actually belongs to
`purchase_order_id` and that `quantity_received` does not exceed what's
still outstanding on that line before persisting.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field

from app.db.models.enums import GoodsReceiptStatus
from app.schemas.common import APIModel


class GoodsReceiptLineCreate(APIModel):
    purchase_order_line_id: uuid.UUID
    quantity_received: Decimal = Field(gt=0)


class GoodsReceiptLineRead(APIModel):
    id: uuid.UUID
    purchase_order_line_id: uuid.UUID
    quantity_received: Decimal


class GoodsReceiptCreate(APIModel):
    grpo_number: str = Field(min_length=1, max_length=64)
    purchase_order_id: uuid.UUID
    received_date: date
    lines: list[GoodsReceiptLineCreate] = Field(min_length=1)


class GoodsReceiptRead(APIModel):
    id: uuid.UUID
    grpo_number: str
    purchase_order_id: uuid.UUID
    status: GoodsReceiptStatus
    received_date: date
    sap_doc_entry: int | None
    lines: list[GoodsReceiptLineRead]
