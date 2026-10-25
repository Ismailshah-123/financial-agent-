"""
app.api.v1.router
==================
Aggregates every v1 sub-router into a single `api_router` that
`app.main` mounts once under `settings.app.api_v1_prefix`. New domain
routers get included here as they're built — this file is the one
place that has to change, not `main.py`.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    agents,
    audit_logs,
    aging,
    ap_priority,
    approval_requests,
    ar_invoices,
    auth,
    bank_reconciliation,
    budgets,
    credit_memos,
    customers,
    fbr_remittances,
    goods_receipts,
    health,
    incoming_payments,
    invoices,
    payments,
    period_close,
    purchase_orders,
    reports,
    sap,
    tax_codes,
    vendors,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(audit_logs.router)
api_router.include_router(auth.router)
api_router.include_router(vendors.router)
api_router.include_router(customers.router)
api_router.include_router(purchase_orders.router)
api_router.include_router(goods_receipts.router)
api_router.include_router(invoices.router)
api_router.include_router(ap_priority.router)
api_router.include_router(ar_invoices.router)
api_router.include_router(aging.router)
api_router.include_router(credit_memos.router)
api_router.include_router(payments.router)
api_router.include_router(incoming_payments.router)
api_router.include_router(reports.router)
api_router.include_router(tax_codes.router)
api_router.include_router(period_close.router)
api_router.include_router(bank_reconciliation.router)
api_router.include_router(budgets.router)
api_router.include_router(fbr_remittances.router)
api_router.include_router(approval_requests.router)
api_router.include_router(agents.router)
api_router.include_router(sap.router)
