"""
app.schemas.common
===================
Base Pydantic config and reusable response shapes shared across every
domain schema module (vendor, invoice, purchase_order, ...).

`APIModel` sets `from_attributes=True` once, here, so every `*Read`
schema can be built directly from an ORM instance
(`VendorRead.model_validate(vendor_row)`) without repeating that config
in every file. `PaginatedResponse` is a generic envelope so list
endpoints have a consistent shape (`items`, `total`, `page`, `page_size`)
across the whole API instead of each router inventing its own.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

T = TypeVar("T")


class APIModel(BaseModel):
    """Base class for every request/response schema in `app.schemas`."""

    model_config = ConfigDict(from_attributes=True)


class PaginationParams(APIModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginatedResponse(APIModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)
