"""
app.services.sap_sync_service
================================
Orchestrates syncing master data (Vendors, Customers) to SAP Business
One via `SAPServiceLayerClient`, using the pure mapping functions in
`app.integrations.sap.mappers`. This is the layer that knows about both
a database session (repositories) and the SAP client — neither of
those two things should know about each other directly.

SYNC STRATEGY: CREATE-OR-DIFF, NEVER SILENT OVERWRITE
------------------------------------------------------------
`sync_vendor` checks `vendor.sap_business_partner_code`:
    - Not set -> this is the first sync. POST a new BusinessPartner to
      SAP, then persist the returned/generated CardCode locally.
    - Set -> fetch the current record from SAP, diff it against what
      this platform would send (`diff_business_partner_fields`), and:
        - No diff -> nothing to do, return without a SAP write.
        - Diff found -> do NOT silently overwrite either side. Return
          the diff so the caller (`SAPIntegrationAgent`) can reason
          about it and require human approval before anything changes.
          This is the same "AI never transacts without approval"
          discipline applied to a sync conflict, not just a financial
          one — an automatic overwrite here could silently erase a
          change someone made directly in SAP.

This service does the mechanical parts (call the mapper, call the
client, persist results); it does NOT decide whether a conflict is
acceptable to auto-resolve — that judgment call belongs to
`SAPIntegrationAgent`, the one thing in this flow allowed to produce an
`AgentDecision`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_audit_logger, get_logger
from app.core.sap_reference import SAPServiceLayerResource
from app.integrations.sap.client import SAPServiceLayerClient
from app.integrations.sap.exceptions import SAPRequestError, SAPPotentialDuplicateError
from app.integrations.sap.document_mappers import (
    ap_invoice_to_sap,
    ar_credit_memo_to_sap,
    ar_invoice_to_sap,
    incoming_payment_to_sap,
    outgoing_payment_to_sap,
    purchase_order_to_sap,
    sap_document_response_to_doc_entry,
)
from app.integrations.sap.mappers import (
    customer_to_sap_business_partner,
    diff_business_partner_fields,
    sap_business_partner_to_customer_fields,
    sap_business_partner_to_vendor_fields,
    vendor_to_sap_business_partner,
)
from app.repositories.ar_invoice_repository import ARInvoiceRepository
from app.repositories.credit_memo_repository import ARCreditMemoRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.incoming_payment_repository import IncomingPaymentRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.purchase_order_repository import PurchaseOrderRepository
from app.repositories.vendor_repository import VendorRepository

logger = get_logger(__name__)


@dataclass
class SyncOutcome:
    """Result of one sync attempt — what `SAPIntegrationAgent` reasons
    about to build its `AgentDecision`. `sap_card_code` is populated for
    master-data (Vendor/Customer) syncs; `sap_doc_entry` for document
    (PurchaseOrder/Invoice) syncs — a given outcome only ever populates
    the one relevant to what was synced."""

    entity_type: str
    entity_id: uuid.UUID
    action: str  # "created" | "no_change" | "conflict" | "failed" | "reconciliation_required"
    sap_card_code: str | None = None
    sap_doc_entry: int | None = None
    conflicting_fields: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    error_message: str | None = None


class SAPSyncService:
    def __init__(self, session: AsyncSession, sap_client: SAPServiceLayerClient) -> None:
        self.session = session
        self.sap_client = sap_client
        self.vendor_repository = VendorRepository(session)
        self.customer_repository = CustomerRepository(session)
        self.purchase_order_repository = PurchaseOrderRepository(session)
        self.invoice_repository = InvoiceRepository(session)
        self.ar_invoice_repository = ARInvoiceRepository(session)
        self.ar_credit_memo_repository = ARCreditMemoRepository(session)
        self.payment_repository = PaymentRepository(session)
        self.incoming_payment_repository = IncomingPaymentRepository(session)

    async def sync_vendor(self, vendor_id: uuid.UUID, *, actor_id: str) -> SyncOutcome:
        vendor = await self.vendor_repository.get_by_id_for_update(vendor_id)
        if vendor is None:
            raise ValueError(f"Vendor {vendor_id} not found.")
        local_payload = vendor_to_sap_business_partner(vendor)

        if not vendor.sap_business_partner_code:
            return await self._create_business_partner(
                entity_type="vendor",
                entity_id=vendor.id,
                local_payload=local_payload,
                repository=self.vendor_repository,
                instance=vendor,
                actor_id=actor_id,
                field_mapper=sap_business_partner_to_vendor_fields,
            )

        return await self._diff_against_sap(
            entity_type="vendor",
            entity_id=vendor.id,
            card_code=vendor.sap_business_partner_code,
            local_payload=local_payload,
        )

    async def sync_customer(self, customer_id: uuid.UUID, *, actor_id: str) -> SyncOutcome:
        customer = await self.customer_repository.get_by_id_for_update(customer_id)
        if customer is None:
            raise ValueError(f"Customer {customer_id} not found.")
        local_payload = customer_to_sap_business_partner(customer)

        if not customer.sap_business_partner_code:
            return await self._create_business_partner(
                entity_type="customer",
                entity_id=customer.id,
                local_payload=local_payload,
                repository=self.customer_repository,
                instance=customer,
                actor_id=actor_id,
                field_mapper=sap_business_partner_to_customer_fields,
            )

        return await self._diff_against_sap(
            entity_type="customer",
            entity_id=customer.id,
            card_code=customer.sap_business_partner_code,
            local_payload=local_payload,
        )

    async def sync_purchase_order(self, po_id: uuid.UUID, *, actor_id: str) -> SyncOutcome:
        """Documents are create-once in this phase — unlike master data,
        there is no diff/update path here yet (see module docstring's
        general strategy note; a posted PO in SAP is not something this
        platform attempts to reconcile field-by-field once created,
        since PO amendment after sending to a vendor is a business
        process with its own rules SAP itself enforces, not something
        to silently overwrite via sync). A PO with `sap_doc_entry`
        already set returns `no_change`."""
        po = await self.purchase_order_repository.get_by_id_with_lines_for_update(po_id)
        if po is None:
            return SyncOutcome(
                entity_type="purchase_order",
                entity_id=po_id,
                action="failed",
                error_message="Purchase order not found.",
            )

        if po.sap_doc_entry is not None:
            return SyncOutcome(
                entity_type="purchase_order",
                entity_id=po.id,
                action="no_change",
                sap_doc_entry=po.sap_doc_entry,
            )

        vendor = await self.vendor_repository.get_by_id_or_raise(po.vendor_id)
        if not vendor.sap_business_partner_code:
            return SyncOutcome(
                entity_type="purchase_order",
                entity_id=po.id,
                action="failed",
                error_message=(
                    "The vendor for this purchase order has not been synced to SAP "
                    "yet. Sync the vendor first (sync_vendor), then retry."
                ),
            )

        payload = purchase_order_to_sap(po, vendor_card_code=vendor.sap_business_partner_code)
        try:
            response = await self.sap_client.post(SAPServiceLayerResource.PURCHASE_ORDERS, payload)
        except SAPRequestError as exc:
            logger.error("sap_sync_create_failed", entity_type="purchase_order", entity_id=str(po.id))
            return SyncOutcome(
                entity_type="purchase_order",
                entity_id=po.id,
                action="failed",
                error_message=exc.sap_error_message or str(exc),
            )

        doc_entry = sap_document_response_to_doc_entry(response)
        await self.purchase_order_repository.update(po, sap_doc_entry=doc_entry)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="sap_sync.purchase_order.create",
            resource_type="purchase_order",
            resource_id=str(po.id),
            outcome="success",
            metadata={"sap_doc_entry": doc_entry},
        )
        logger.info("sap_sync_created", entity_type="purchase_order", entity_id=str(po.id), doc_entry=doc_entry)
        return SyncOutcome(
            entity_type="purchase_order", entity_id=po.id, action="created", sap_doc_entry=doc_entry
        )

    async def sync_ap_invoice(self, invoice_id: uuid.UUID, *, actor_id: str) -> SyncOutcome:
        """Same create-once strategy as `sync_purchase_order`. If the
        invoice is linked to a purchase order, that PO must already be
        synced (`sap_doc_entry` set) for the invoice to carry SAP's
        base-document linkage — if it isn't, this still creates the
        invoice in SAP, just as a standalone document (matching
        `MatchType.MANUAL`/`TWO_WAY` semantics — see
        `app.integrations.sap.document_mappers.ap_invoice_to_sap`'s
        docstring on why a missing link is a safe fallback, not an
        error)."""
        invoice = await self.invoice_repository.get_by_id_with_lines_for_update(invoice_id)
        if invoice is None:
            return SyncOutcome(
                entity_type="ap_invoice",
                entity_id=invoice_id,
                action="failed",
                error_message="Invoice not found.",
            )

        if invoice.sap_doc_entry is not None:
            return SyncOutcome(
                entity_type="ap_invoice",
                entity_id=invoice.id,
                action="no_change",
                sap_doc_entry=invoice.sap_doc_entry,
            )

        vendor = await self.vendor_repository.get_by_id_or_raise(invoice.vendor_id)
        if not vendor.sap_business_partner_code:
            return SyncOutcome(
                entity_type="ap_invoice",
                entity_id=invoice.id,
                action="failed",
                error_message=(
                    "The vendor for this invoice has not been synced to SAP yet. "
                    "Sync the vendor first (sync_vendor), then retry."
                ),
            )

        po_doc_entry: int | None = None
        po_line_numbers_by_local_line_id: dict[uuid.UUID, int] = {}
        if invoice.purchase_order_id is not None:
            po = await self.purchase_order_repository.get_by_id_with_lines(invoice.purchase_order_id)
            if po is not None and po.sap_doc_entry is not None:
                po_doc_entry = po.sap_doc_entry
                po_line_numbers_by_local_line_id = {line.id: line.line_number for line in po.lines}

        payload = ap_invoice_to_sap(
            invoice,
            vendor_card_code=vendor.sap_business_partner_code,
            purchase_order_sap_doc_entry=po_doc_entry,
            po_line_numbers_by_local_line_id=po_line_numbers_by_local_line_id,
        )
        try:
            response = await self.sap_client.post(SAPServiceLayerResource.PURCHASE_INVOICES, payload)
        except SAPPotentialDuplicateError as exc:
            logger.error("sap_sync_unknown_outcome", entity_type="ap_invoice", entity_id=str(invoice.id))
            return SyncOutcome(entity_type="ap_invoice", entity_id=invoice.id, action="reconciliation_required", error_message=str(exc))
        except SAPRequestError as exc:
            logger.error("sap_sync_create_failed", entity_type="ap_invoice", entity_id=str(invoice.id))
            return SyncOutcome(entity_type="ap_invoice", entity_id=invoice.id, action="failed", error_message=exc.sap_error_message or str(exc))

        doc_entry = sap_document_response_to_doc_entry(response)
        await self.invoice_repository.update(invoice, sap_doc_entry=doc_entry)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="sap_sync.ap_invoice.create",
            resource_type="ap_invoice",
            resource_id=str(invoice.id),
            outcome="success",
            metadata={"sap_doc_entry": doc_entry, "linked_to_po": po_doc_entry is not None},
        )
        logger.info(
            "sap_sync_created", entity_type="ap_invoice", entity_id=str(invoice.id), doc_entry=doc_entry
        )
        return SyncOutcome(
            entity_type="ap_invoice", entity_id=invoice.id, action="created", sap_doc_entry=doc_entry
        )

    async def sync_ar_invoice(self, ar_invoice_id: uuid.UUID, *, actor_id: str) -> SyncOutcome:
        """Create-once, same strategy as the AP document syncs. Requires
        the customer already synced to SAP first."""
        ar_invoice = await self.ar_invoice_repository.get_by_id_with_lines_for_update(ar_invoice_id)
        if ar_invoice is None:
            return SyncOutcome(
                entity_type="ar_invoice",
                entity_id=ar_invoice_id,
                action="failed",
                error_message="AR invoice not found.",
            )

        if ar_invoice.sap_doc_entry is not None:
            return SyncOutcome(
                entity_type="ar_invoice",
                entity_id=ar_invoice.id,
                action="no_change",
                sap_doc_entry=ar_invoice.sap_doc_entry,
            )

        customer = await self.customer_repository.get_by_id_or_raise(ar_invoice.customer_id)
        if not customer.sap_business_partner_code:
            return SyncOutcome(
                entity_type="ar_invoice",
                entity_id=ar_invoice.id,
                action="failed",
                error_message=(
                    "The customer for this invoice has not been synced to SAP yet. "
                    "Sync the customer first (sync_customer), then retry."
                ),
            )

        payload = ar_invoice_to_sap(
            ar_invoice, customer_card_code=customer.sap_business_partner_code
        )
        try:
            response = await self.sap_client.post(SAPServiceLayerResource.INVOICES, payload)
        except SAPPotentialDuplicateError as exc:
            logger.error("sap_sync_unknown_outcome", entity_type="ar_invoice", entity_id=str(ar_invoice.id))
            return SyncOutcome(entity_type="ar_invoice", entity_id=ar_invoice.id, action="reconciliation_required", error_message=str(exc))
        except SAPRequestError as exc:
            logger.error("sap_sync_create_failed", entity_type="ar_invoice", entity_id=str(ar_invoice.id))
            return SyncOutcome(entity_type="ar_invoice", entity_id=ar_invoice.id, action="failed", error_message=exc.sap_error_message or str(exc))

        doc_entry = sap_document_response_to_doc_entry(response)
        await self.ar_invoice_repository.update(ar_invoice, sap_doc_entry=doc_entry)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="sap_sync.ar_invoice.create",
            resource_type="ar_invoice",
            resource_id=str(ar_invoice.id),
            outcome="success",
            metadata={"sap_doc_entry": doc_entry},
        )
        logger.info(
            "sap_sync_created", entity_type="ar_invoice", entity_id=str(ar_invoice.id), doc_entry=doc_entry
        )
        return SyncOutcome(
            entity_type="ar_invoice", entity_id=ar_invoice.id, action="created", sap_doc_entry=doc_entry
        )

    async def sync_ar_credit_memo(self, credit_memo_id: uuid.UUID, *, actor_id: str) -> SyncOutcome:
        """Create-once. Sent as a standalone SAP document regardless of
        whether `related_ar_invoice_id` is set — see
        `app.integrations.sap.document_mappers.ar_credit_memo_to_sap`'s
        docstring for why line-level linkage isn't attempted."""
        memo = await self.ar_credit_memo_repository.get_by_id_with_lines(credit_memo_id)
        if memo is None:
            return SyncOutcome(
                entity_type="ar_credit_memo",
                entity_id=credit_memo_id,
                action="failed",
                error_message="AR credit memo not found.",
            )

        if memo.sap_doc_entry is not None:
            return SyncOutcome(
                entity_type="ar_credit_memo",
                entity_id=memo.id,
                action="no_change",
                sap_doc_entry=memo.sap_doc_entry,
            )

        customer = await self.customer_repository.get_by_id_or_raise(memo.customer_id)
        if not customer.sap_business_partner_code:
            return SyncOutcome(
                entity_type="ar_credit_memo",
                entity_id=memo.id,
                action="failed",
                error_message=(
                    "The customer for this credit memo has not been synced to SAP "
                    "yet. Sync the customer first (sync_customer), then retry."
                ),
            )

        payload = ar_credit_memo_to_sap(memo, customer_card_code=customer.sap_business_partner_code)
        try:
            response = await self.sap_client.post(SAPServiceLayerResource.CREDIT_NOTES, payload)
        except SAPRequestError as exc:
            logger.error(
                "sap_sync_create_failed", entity_type="ar_credit_memo", entity_id=str(memo.id)
            )
            return SyncOutcome(
                entity_type="ar_credit_memo",
                entity_id=memo.id,
                action="failed",
                error_message=exc.sap_error_message or str(exc),
            )

        doc_entry = sap_document_response_to_doc_entry(response)
        await self.ar_credit_memo_repository.update(memo, sap_doc_entry=doc_entry)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="sap_sync.ar_credit_memo.create",
            resource_type="ar_credit_memo",
            resource_id=str(memo.id),
            outcome="success",
            metadata={"sap_doc_entry": doc_entry},
        )
        logger.info(
            "sap_sync_created", entity_type="ar_credit_memo", entity_id=str(memo.id), doc_entry=doc_entry
        )
        return SyncOutcome(
            entity_type="ar_credit_memo", entity_id=memo.id, action="created", sap_doc_entry=doc_entry
        )

    async def sync_outgoing_payment(self, payment_id: uuid.UUID, *, actor_id: str) -> SyncOutcome:
        """Syncs an AP payment (money that left the company) to SAP as a
        `VendorPayments` document, applied against the settled invoice's
        own SAP `DocEntry`. Requires, in order:
            1. `settings.sap.default_cash_account_code` configured — a
               real SAP G/L account code, never guessed (see that
               setting's docstring).
            2. The vendor already synced to SAP.
            3. The settled AP invoice already synced to SAP (a payment
               cannot be linked to an invoice SAP doesn't know about).
        Create-once, same as every other document sync in this service —
        a payment with `sap_doc_entry` already set returns `no_change`.
        """
        payment = await self.payment_repository.get_by_id_for_update(payment_id)
        if payment is None:
            return SyncOutcome(
                entity_type="outgoing_payment",
                entity_id=payment_id,
                action="failed",
                error_message="Payment not found.",
            )

        if payment.sap_doc_entry is not None:
            return SyncOutcome(
                entity_type="outgoing_payment",
                entity_id=payment.id,
                action="no_change",
                sap_doc_entry=payment.sap_doc_entry,
            )

        cash_account_code = settings.sap.default_cash_account_code
        if not cash_account_code:
            return SyncOutcome(
                entity_type="outgoing_payment",
                entity_id=payment.id,
                action="failed",
                error_message=(
                    "SAP_DEFAULT_CASH_ACCOUNT_CODE is not configured. A real SAP "
                    "G/L account code is required before any payment can sync — "
                    "see app.core.config.SAPSettings.default_cash_account_code."
                ),
            )

        vendor = await self.vendor_repository.get_by_id_or_raise(payment.vendor_id)
        if not vendor.sap_business_partner_code:
            return SyncOutcome(
                entity_type="outgoing_payment",
                entity_id=payment.id,
                action="failed",
                error_message=(
                    "The vendor for this payment has not been synced to SAP yet. "
                    "Sync the vendor first, then retry."
                ),
            )

        invoice = await self.invoice_repository.get_by_id_or_raise(payment.invoice_id)
        if invoice.sap_doc_entry is None:
            return SyncOutcome(
                entity_type="outgoing_payment",
                entity_id=payment.id,
                action="failed",
                error_message=(
                    "The AP invoice this payment settles has not been synced to "
                    "SAP yet. Sync the invoice first (sync_ap_invoice), then retry."
                ),
            )

        payload = outgoing_payment_to_sap(
            payment,
            vendor_card_code=vendor.sap_business_partner_code,
            ap_invoice_sap_doc_entry=invoice.sap_doc_entry,
            cash_account_code=cash_account_code,
        )
        try:
            response = await self.sap_client.post(SAPServiceLayerResource.VENDOR_PAYMENTS, payload)
        except SAPPotentialDuplicateError as exc:
            logger.error("sap_sync_unknown_outcome", entity_type="outgoing_payment", entity_id=str(payment.id))
            return SyncOutcome(
                entity_type="outgoing_payment",
                entity_id=payment.id,
                action="reconciliation_required",
                error_message=str(exc),
            )
        except SAPRequestError as exc:
            logger.error("sap_sync_create_failed", entity_type="outgoing_payment", entity_id=str(payment.id))
            return SyncOutcome(
                entity_type="outgoing_payment",
                entity_id=payment.id,
                action="failed",
                error_message=exc.sap_error_message or str(exc),
            )

        doc_entry = sap_document_response_to_doc_entry(response)
        await self.payment_repository.update(payment, sap_doc_entry=doc_entry)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="sap_sync.outgoing_payment.create",
            resource_type="outgoing_payment",
            resource_id=str(payment.id),
            outcome="success",
            metadata={"sap_doc_entry": doc_entry, "applied_to_invoice_doc_entry": invoice.sap_doc_entry},
        )
        logger.info(
            "sap_sync_created",
            entity_type="outgoing_payment",
            entity_id=str(payment.id),
            doc_entry=doc_entry,
        )
        return SyncOutcome(
            entity_type="outgoing_payment", entity_id=payment.id, action="created", sap_doc_entry=doc_entry
        )

    async def sync_incoming_payment(self, payment_id: uuid.UUID, *, actor_id: str) -> SyncOutcome:
        """AR mirror of `sync_outgoing_payment` — syncs a customer
        payment to SAP as an `IncomingPayments` document, applied
        against the settled AR invoice's own SAP `DocEntry`. Same
        three-step prerequisite chain (cash account configured, customer
        synced, AR invoice synced), same create-once behavior."""
        payment = await self.incoming_payment_repository.get_by_id_for_update(payment_id)
        if payment is None:
            return SyncOutcome(
                entity_type="incoming_payment",
                entity_id=payment_id,
                action="failed",
                error_message="Incoming payment not found.",
            )

        if payment.sap_doc_entry is not None:
            return SyncOutcome(
                entity_type="incoming_payment",
                entity_id=payment.id,
                action="no_change",
                sap_doc_entry=payment.sap_doc_entry,
            )

        cash_account_code = settings.sap.default_cash_account_code
        if not cash_account_code:
            return SyncOutcome(
                entity_type="incoming_payment",
                entity_id=payment.id,
                action="failed",
                error_message=(
                    "SAP_DEFAULT_CASH_ACCOUNT_CODE is not configured. A real SAP "
                    "G/L account code is required before any payment can sync — "
                    "see app.core.config.SAPSettings.default_cash_account_code."
                ),
            )

        customer = await self.customer_repository.get_by_id_or_raise(payment.customer_id)
        if not customer.sap_business_partner_code:
            return SyncOutcome(
                entity_type="incoming_payment",
                entity_id=payment.id,
                action="failed",
                error_message=(
                    "The customer for this payment has not been synced to SAP yet. "
                    "Sync the customer first, then retry."
                ),
            )

        ar_invoice = await self.ar_invoice_repository.get_by_id_or_raise(payment.ar_invoice_id)
        if ar_invoice.sap_doc_entry is None:
            return SyncOutcome(
                entity_type="incoming_payment",
                entity_id=payment.id,
                action="failed",
                error_message=(
                    "The AR invoice this payment settles has not been synced to "
                    "SAP yet. Sync the invoice first (sync_ar_invoice), then retry."
                ),
            )

        payload = incoming_payment_to_sap(
            payment,
            customer_card_code=customer.sap_business_partner_code,
            ar_invoice_sap_doc_entry=ar_invoice.sap_doc_entry,
            cash_account_code=cash_account_code,
        )
        try:
            response = await self.sap_client.post(SAPServiceLayerResource.INCOMING_PAYMENTS, payload)
        except SAPPotentialDuplicateError as exc:
            logger.error("sap_sync_unknown_outcome", entity_type="incoming_payment", entity_id=str(payment.id))
            return SyncOutcome(entity_type="incoming_payment", entity_id=payment.id, action="reconciliation_required", error_message=str(exc))
        except SAPRequestError as exc:
            logger.error("sap_sync_create_failed", entity_type="incoming_payment", entity_id=str(payment.id))
            return SyncOutcome(entity_type="incoming_payment", entity_id=payment.id, action="failed", error_message=exc.sap_error_message or str(exc))

        doc_entry = sap_document_response_to_doc_entry(response)
        await self.incoming_payment_repository.update(payment, sap_doc_entry=doc_entry)

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action="sap_sync.incoming_payment.create",
            resource_type="incoming_payment",
            resource_id=str(payment.id),
            outcome="success",
            metadata={
                "sap_doc_entry": doc_entry,
                "applied_to_invoice_doc_entry": ar_invoice.sap_doc_entry,
            },
        )
        logger.info(
            "sap_sync_created",
            entity_type="incoming_payment",
            entity_id=str(payment.id),
            doc_entry=doc_entry,
        )
        return SyncOutcome(
            entity_type="incoming_payment", entity_id=payment.id, action="created", sap_doc_entry=doc_entry
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _create_business_partner(
        self,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        local_payload: dict,
        repository: Any,
        instance: Any,
        actor_id: str,
        field_mapper: Callable[[dict], dict],
    ) -> SyncOutcome:
        try:
            response = await self.sap_client.post(
                SAPServiceLayerResource.BUSINESS_PARTNERS, local_payload
            )
        except SAPPotentialDuplicateError as exc:
            logger.error("sap_sync_unknown_outcome", entity_type=entity_type, entity_id=str(entity_id))
            return SyncOutcome(entity_type=entity_type, entity_id=entity_id, action="reconciliation_required", error_message=str(exc))
        except SAPRequestError as exc:
            logger.error("sap_sync_create_failed", entity_type=entity_type, entity_id=str(entity_id))
            return SyncOutcome(entity_type=entity_type, entity_id=entity_id, action="failed", error_message=exc.sap_error_message or str(exc))

        card_code = response.get("CardCode", local_payload["CardCode"])
        await repository.update(instance, **field_mapper(response or local_payload))

        await get_audit_logger().record(session=self.session, 
            actor_id=actor_id,
            action=f"sap_sync.{entity_type}.create",
            resource_type=entity_type,
            resource_id=str(entity_id),
            outcome="success",
            metadata={"sap_card_code": card_code},
        )
        logger.info(
            "sap_sync_created", entity_type=entity_type, entity_id=str(entity_id), card_code=card_code
        )
        return SyncOutcome(
            entity_type=entity_type, entity_id=entity_id, action="created", sap_card_code=card_code
        )

    async def _diff_against_sap(
        self, *, entity_type: str, entity_id: uuid.UUID, card_code: str, local_payload: dict
    ) -> SyncOutcome:
        try:
            sap_current = await self.sap_client.get(
                SAPServiceLayerResource.BUSINESS_PARTNERS, card_code
            )
        except SAPRequestError as exc:
            return SyncOutcome(
                entity_type=entity_type,
                entity_id=entity_id,
                action="failed",
                sap_card_code=card_code,
                error_message=exc.sap_error_message or str(exc),
            )

        diffs = diff_business_partner_fields(local_payload=local_payload, sap_current=sap_current)
        if not diffs:
            return SyncOutcome(
                entity_type=entity_type,
                entity_id=entity_id,
                action="no_change",
                sap_card_code=card_code,
            )
        return SyncOutcome(
            entity_type=entity_type,
            entity_id=entity_id,
            action="conflict",
            sap_card_code=card_code,
            conflicting_fields=diffs,
        )
