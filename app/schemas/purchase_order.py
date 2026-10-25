"""
app.schemas.purchase_order
============================
Request/response shapes for Purchase Orders. `total_amount` on
`PurchaseOrderCreate` is deliberately NOT accepted from the client — it
is always computed server-side from the sum of line totals
(`app.services.purchase_order_service`, next phase) to prevent a caller
from submitting a PO whose header total doesn't match its lines, which
would silently corrupt every downstream 3-way match.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field, field_validator

from app.core.constants import Currency
from app.db.models.enums import PurchaseOrderStatus
from app.schemas.common import APIModel


class PurchaseOrderLineCreate(APIModel):
    line_number: int = Field(ge=1)
    item_code: str | None = Field(default=None, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    quantity_ordered: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)

    @property
    def line_total(self) -> Decimal:
        return self.quantity_ordered * self.unit_price


class PurchaseOrderLineRead(APIModel):
    id: uuid.UUID
    line_number: int
    item_code: str | None
    description: str
    quantity_ordered: Decimal
    unit_price: Decimal
    line_total: Decimal


class PurchaseOrderCreate(APIModel):
    po_number: str = Field(min_length=1, max_length=64)
    vendor_id: uuid.UUID
    currency: Currency
    order_date: date
    expected_delivery_date: date | None = None
    lines: list[PurchaseOrderLineCreate] = Field(min_length=1)

    @field_validator("lines")
    @classmethod
    def _unique_line_numbers(
        cls, lines: list[PurchaseOrderLineCreate]
    ) -> list[PurchaseOrderLineCreate]:
        numbers = [line.line_number for line in lines]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Purchase order line numbers must be unique.")
        return lines


class PurchaseOrderRead(APIModel):
    id: uuid.UUID
    po_number: str
    vendor_id: uuid.UUID
    status: PurchaseOrderStatus
    currency: Currency
    total_amount: Decimal
    order_date: date
    expected_delivery_date: date | None
    sap_doc_entry: int | None
    lines: list[PurchaseOrderLineRead]
