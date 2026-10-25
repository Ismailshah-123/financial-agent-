"""
app.db.models.payment
======================
`OutgoingPayment`: a scheduled or executed payment to a vendor against
one invoice. Kept 1:1 with an invoice for this foundation phase (one
payment fully settles one invoice) — partial payments and payment runs
that batch multiple invoices into one bank transaction are a Phase 2
Treasury Agent concern and will need a join table (`payment_invoices`)
when they're built; not modeled now to avoid speculative schema that
might not match how Treasury actually needs to batch.

`status` transitions are intentionally narrow (`SCHEDULED` ->
`PENDING_APPROVAL` -> `APPROVED` -> `EXECUTING` -> `EXECUTED`/`FAILED`)
because a payment is the single most consequential, least-reversible
action in the whole AP flow — see `RollbackStrategy.is_reversible` in
app.agents.schemas, which the AP agent sets to `False` once a payment
reaches `EXECUTED`.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Currency
from app.db.base import AuditMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.enums import PaymentStatus


class OutgoingPayment(Base, UUIDPrimaryKeyMixin, TimestampMixin, AuditMixin):
    __tablename__ = "outgoing_payments"

    payment_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False, index=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, unique=True, index=True
    )

    status: Mapped[PaymentStatus] = mapped_column(
        String(32), nullable=False, default=PaymentStatus.SCHEDULED.value, index=True
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        doc="NET amount actually transferred to the vendor — invoice total "
        "minus withholding_tax_amount when withholding applies (see "
        "withholding_tax_amount below). Equals the invoice total when no "
        "withholding tax code was supplied at scheduling time.",
    )
    currency: Mapped[Currency] = mapped_column(String(3), nullable=False)
    payment_method: Mapped[str] = mapped_column(
        String(32), nullable=False, doc="e.g. 'bank_transfer', 'check', 'wire'."
    )

    withholding_tax_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="TaxCode.code used to compute withholding, if any. NULL means "
        "no withholding was applied to this payment.",
    )
    withholding_tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=0,
        doc="Amount withheld from the vendor and owed to the tax authority "
        "instead — invoice_total = amount (net) + withholding_tax_amount.",
    )

    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    executed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bank_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    sap_doc_entry: Mapped[int | None] = mapped_column(nullable=True)

    vendor: Mapped["Vendor"] = relationship()  # noqa: F821
    invoice: Mapped["Invoice"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OutgoingPayment id={self.id} payment_number={self.payment_number!r} status={self.status}>"
