"""
app.services.tax_service
===========================
Tax calculation for two fundamentally different mechanisms — see
`TaxType`'s docstring in `app.db.models.enums` for the conceptual
distinction before reading further:

    - SALES TAX (e.g. Pakistan's federal GST under the Sales Tax Act
      1990, or a provincial Sales Tax on Services): ADDED on top of an
      invoice subtotal. `calculate_sales_tax` is what
      `InvoiceService`/`ARInvoiceService` would call to compute
      `tax_amount` when a `tax_code` is supplied instead of a
      client-provided flat number.

    - WITHHOLDING TAX (e.g. Pakistan's Section 153 withholding under
      the Income Tax Ordinance 2001): DEDUCTED from a payment before it
      reaches the payee; the withheld amount is remitted to the tax
      authority separately, not paid to the vendor. It never appears on
      the invoice itself — it only affects how much of an already-
      billed amount actually gets transferred at payment time.
      `calculate_withholding_tax` computes the amount to withhold;
      wiring this into `PaymentService.execute_payment` (reducing the
      actual bank transfer and posting a separate WHT-payable-to-FBR
      liability) is a natural next integration step, deliberately not
      done automatically here — a company's WHT obligation depends on
      the vendor's filer status and transaction category, which this
      platform doesn't yet capture on the `Vendor` model, so silently
      applying withholding on every payment would risk being wrong.

RATES ARE EFFECTIVE-DATED, LOOKED UP AS-OF THE RELEVANT DOCUMENT DATE
--------------------------------------------------------------------------
An invoice or payment always calculates tax using the rate in effect on
ITS OWN date (`invoice_date`, `payment_date`), not today's rate — see
`TaxCodeRepository.get_effective_rate` and `TaxCode.covers`. This
matters for anything processed after a rate change but dated in the
prior period.

*** SEEDED RATES ARE A STARTING POINT — VERIFY BEFORE REAL TAX FILINGS.
See app/db/models/tax_code.py's docstring and
alembic/versions/0005_tax_codes.py for the full caveat. This platform
computes tax; it does not, and cannot, guarantee the seeded rates match
current FBR (or any other jurisdiction's) notified rates at any given
moment. ***

ROUNDING
--------
Tax amounts round to 2 decimal places using ROUND_HALF_UP (standard
"round half away from zero" — the common convention in commercial tax
calculation, as opposed to Python's default banker's rounding), via
`compute_tax_amount`, which is the one pure, DB-free function in this
module and therefore the one directly unit-tested without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.enums import TaxType
from app.db.models.tax_code import TaxCode
from app.repositories.tax_code_repository import TaxCodeRepository


@dataclass
class TaxCalculationResult:
    tax_code: str
    tax_type: TaxType
    rate_percent: Decimal
    base_amount: Decimal
    tax_amount: Decimal


def compute_tax_amount(*, base_amount: Decimal, rate_percent: Decimal) -> Decimal:
    """Pure. `rate_percent` is e.g. Decimal('18.000') for 18%. Rounds to
    2 decimal places using ROUND_HALF_UP, the standard convention for
    commercial tax calculation."""
    raw = base_amount * rate_percent / Decimal("100")
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class TaxCalculationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tax_code_repository = TaxCodeRepository(session)

    async def calculate_sales_tax(
        self, *, subtotal: Decimal, tax_code: str, as_of: date
    ) -> TaxCalculationResult:
        """`subtotal` is the pre-tax invoice amount; the result's
        `tax_amount` is what gets added to produce the invoice total."""
        code_row = await self._get_effective_code(
            code=tax_code, as_of=as_of, expected_type=TaxType.SALES_TAX
        )
        tax_amount = compute_tax_amount(base_amount=subtotal, rate_percent=code_row.rate_percent)
        return TaxCalculationResult(
            tax_code=code_row.code,
            tax_type=TaxType.SALES_TAX,
            rate_percent=code_row.rate_percent,
            base_amount=subtotal,
            tax_amount=tax_amount,
        )

    async def calculate_withholding_tax(
        self, *, gross_amount: Decimal, tax_code: str, as_of: date
    ) -> TaxCalculationResult:
        """`gross_amount` is the invoice/payment amount BEFORE
        withholding; the result's `tax_amount` is what gets withheld —
        i.e. `gross_amount - tax_amount` is what actually reaches the
        vendor. See module docstring on why this isn't automatically
        wired into payment execution yet."""
        code_row = await self._get_effective_code(
            code=tax_code, as_of=as_of, expected_type=TaxType.WITHHOLDING_TAX
        )
        tax_amount = compute_tax_amount(
            base_amount=gross_amount, rate_percent=code_row.rate_percent
        )
        return TaxCalculationResult(
            tax_code=code_row.code,
            tax_type=TaxType.WITHHOLDING_TAX,
            rate_percent=code_row.rate_percent,
            base_amount=gross_amount,
            tax_amount=tax_amount,
        )

    async def _get_effective_code(
        self, *, code: str, as_of: date, expected_type: TaxType
    ) -> TaxCode:
        code_row = await self.tax_code_repository.get_effective_rate(code=code, as_of=as_of)
        if code_row is None:
            raise NotFoundError(
                f"No active tax code '{code}' is effective as of {as_of.isoformat()}. "
                f"It may not exist, be inactive, or have expired/not yet started as of "
                f"that date.",
                details={"tax_code": code, "as_of": as_of.isoformat()},
            )
        if TaxType(code_row.tax_type) != expected_type:
            raise NotFoundError(
                f"Tax code '{code}' is a {code_row.tax_type} code, not "
                f"{expected_type.value} — wrong calculation method called for this code.",
                details={"tax_code": code, "actual_type": code_row.tax_type},
            )
        return code_row
