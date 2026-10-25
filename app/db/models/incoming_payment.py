"""
app.db.models.incoming_payment
=================================
`IncomingPayment`: cash received from a customer against an AR invoice.
The AR mirror of `OutgoingPayment`, with one structural difference:
`ar_invoice_id` is NOT unique here (unlike `OutgoingPayment.invoice_id`),
because AR payments are commonly partial — a customer might pay an
invoice across two or three separate remittances, so multiple
`IncomingPayment` rows can legitimately point at the same `ARInvoice`.

`status` goes straight to `EXECUTED` at creation time in this phase — a
simplifying assumption documented here rather than silently baked in:
this platform assumes an `IncomingPayment` record is only created once
a bank deposit has already been confirmed (e.g. via bank feed or manual
reconciliation), not to represent a payment promise or a pending/
unconfirmed clearance. If a future requirement needs to track "customer
says they've paid but funds haven't cleared yet," that argues for a
`PENDING_CLEARANCE` step before `EXECUTED` — not modeled now because
nothing in this platform currently produces that intermediate state.
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


class IncomingPayment(Base, UUIDPrimaryKeyMixin, TimestampMixin, AuditMixin):
    __tablename__ = "incoming_payments"

    payment_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False, index=True
    )
    ar_invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ar_invoices.id"), nullable=False, index=True
    )

    status: Mapped[PaymentStatus] = mapped_column(
        String(32), nullable=False, default=PaymentStatus.EXECUTED.value, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(String(3), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False)

    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    bank_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)

    sap_doc_entry: Mapped[int | None] = mapped_column(nullable=True)

    customer: Mapped["Customer"] = relationship()  # noqa: F821
    ar_invoice: Mapped["ARInvoice"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IncomingPayment id={self.id} payment_number={self.payment_number!r}>"
