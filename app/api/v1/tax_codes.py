"""
app.api.v1.tax_codes
=======================
HTTP endpoints for tax reference data. `POST /tax-codes` requires
`TAX_CODE_MANAGE` (finance leadership only, not routine clerk access —
misconfiguring a tax rate has real financial/compliance consequences).
`POST /tax-codes/calculate` is a preview endpoint: given an amount and
a code, returns what the tax would be, without needing an actual
invoice — useful for finance staff sanity-checking a rate before it's
applied anywhere, and for the frontend to show a live preview while a
user fills out an invoice form.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorContext, require_permission
from app.core.constants import Permission
from app.db.models.enums import TaxType
from app.db.models.tax_code import TaxCode
from app.db.session import get_db
from app.repositories.tax_code_repository import TaxCodeRepository
from app.schemas.tax_code import (
    TaxCalculationRequest,
    TaxCalculationResultRead,
    TaxCodeCreate,
    TaxCodeRead,
)
from app.services.tax_service import TaxCalculationService

router = APIRouter(prefix="/tax-codes", tags=["tax-codes"])


@router.post("", response_model=TaxCodeRead, status_code=status.HTTP_201_CREATED)
async def create_tax_code(
    payload: TaxCodeCreate,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.TAX_CODE_MANAGE)),
) -> TaxCodeRead:
    repository = TaxCodeRepository(session)
    tax_code = TaxCode(
        code=payload.code,
        name=payload.name,
        tax_type=payload.tax_type.value,
        jurisdiction=payload.jurisdiction,
        rate_percent=payload.rate_percent,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        notes=payload.notes,
    )
    tax_code = await repository.add(tax_code)
    await session.commit()
    return TaxCodeRead.model_validate(tax_code)


@router.get("", response_model=list[TaxCodeRead])
async def list_active_tax_codes(
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.TAX_CODE_READ)),
) -> list[TaxCodeRead]:
    repository = TaxCodeRepository(session)
    codes = await repository.list_active()
    return [TaxCodeRead.model_validate(c) for c in codes]


@router.post("/calculate", response_model=TaxCalculationResultRead)
async def calculate_tax(
    payload: TaxCalculationRequest,
    session: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_permission(Permission.TAX_CODE_READ)),
) -> TaxCalculationResultRead:
    service = TaxCalculationService(session)
    if payload.calculation_type == TaxType.SALES_TAX:
        result = await service.calculate_sales_tax(
            subtotal=payload.base_amount, tax_code=payload.tax_code, as_of=payload.as_of
        )
    else:
        result = await service.calculate_withholding_tax(
            gross_amount=payload.base_amount, tax_code=payload.tax_code, as_of=payload.as_of
        )
    return TaxCalculationResultRead.model_validate(result)
