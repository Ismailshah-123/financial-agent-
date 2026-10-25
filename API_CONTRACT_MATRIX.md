# API Contract Matrix

Generated from the route handlers and frontend API client on 2026-10-09. Path and permission data are source-derived; exact JSON field shapes remain defined by the Pydantic response/request schemas and are intentionally not duplicated in this matrix.

Total routes inventoried in the initial snapshot: **81**. Current source has **82 route decorators**, including the added `POST /sap/verify`.

| Method | Path | Auth / Permission | Request body | Query / path inputs | Response annotation | Handler | Frontend consumer | Test evidence | Status |
|---|---|---|---|---|---|---|---|---|---|
| POST | `/agents/accounts-payable/run` | `AGENT_INVOKE` | `payload: RunAccountsPayableAgentRequest` | — | `AgentResult` | `run_accounts_payable_agent` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/agents/accounts-receivable/run` | `AGENT_INVOKE` | `payload: RunAccountsReceivableAgentRequest` | — | `AgentResult` | `run_accounts_receivable_agent` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/agents/bank-reconciliation/run` | `AGENT_INVOKE` | `payload: RunBankReconciliationAgentRequest` | — | `AgentResult` | `run_bank_reconciliation_agent` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/agents/budget-planning/run` | `AGENT_INVOKE` | `payload: RunBudgetPlanningAgentRequest` | — | `AgentResult` | `run_budget_planning_agent` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/agents/catalog` | `AGENT_INVOKE` | `—` | — | `list[AgentCatalogEntry]` | `list_agent_catalog` | frontend/src/pages/Agents.jsx | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/agents/collections/run` | `AGENT_INVOKE` | `payload: RunCollectionsAgentRequest` | — | `AgentResult` | `run_collections_agent` | frontend/src/pages/CustomerDetail.jsx | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/agents/compliance/run` | `AGENT_INVOKE` | `payload: RunComplianceAgentRequest` | — | `AgentResult` | `run_compliance_agent` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/agents/finance-director/run` | `AGENT_INVOKE` | `payload: RunFinanceDirectorAgentRequest` | — | `AgentResult` | `run_finance_director_agent` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/agents/fraud-detection/run` | `AGENT_INVOKE` | `payload: RunFraudDetectionAgentRequest` | — | `AgentResult` | `run_fraud_detection_agent` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/agents/sap-integration/run` | `AGENT_CONFIGURE` | `payload: RunSAPIntegrationAgentRequest` | — | `AgentResult` | `run_sap_integration_agent` | frontend/src/pages/SapIntegration.jsx | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/agents/tax/run` | `AGENT_INVOKE` | `payload: RunTaxAgentRequest` | — | `AgentResult` | `run_tax_agent` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/agents/treasury/run` | `AGENT_INVOKE` | `payload: RunTreasuryAgentRequest` | — | `AgentResult` | `run_treasury_agent` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/aging/customer/{customer_id}` | `AR_INVOICE_READ` | `customer_id: uuid.UUID, as_of: date | None` | — | `CustomerAgingRead` | `get_customer_aging_detail` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| GET | `/aging/customers` | `AR_INVOICE_READ` | `as_of: date | None, risk: PriorityTier | None, priority: PriorityTier | None, minimum_amount: Decimal | None, search: str | None` | pagination | `PaginatedResponse[CustomerAgingRead]` | `list_aging_customers` | frontend/src/pages/Dashboard.jsx, frontend/src/pages/Receivables.jsx | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/aging/invoices` | `AR_INVOICE_READ` | `as_of: date | None, customer_id: uuid.UUID | None, bucket: AgingBucket | None, minimum_amount: Decimal | None, search: str | None` | pagination | `PaginatedResponse[InvoiceAgingRead]` | `list_aging_invoices` | frontend/src/pages/Receivables.jsx | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/aging/summary` | `AR_INVOICE_READ` | `as_of: date | None` | — | `PortfolioAgingSummaryRead` | `get_aging_summary` | frontend/src/pages/Dashboard.jsx, frontend/src/pages/Receivables.jsx | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/ap-priority/obligations` | `INVOICE_READ` | `as_of: date | None, vendor_id: uuid.UUID | None, status: PaymentPriorityStatus | None, priority: PriorityTier | None, minimum_amount: Decimal | None, search: str | None, include_executed: bool` | pagination | `PaginatedResponse[PaymentObligationRead]` | `list_payment_obligations` | frontend/src/pages/Payables.jsx, frontend/src/pages/VendorDetail.tsx | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/ap-priority/summary` | `INVOICE_READ` | `as_of: date | None` | — | `APPrioritySummaryRead` | `get_ap_priority_summary` | frontend/src/pages/Dashboard.jsx, frontend/src/pages/Payables.jsx | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/ap-priority/vendor/{vendor_id}` | `INVOICE_READ` | `vendor_id: uuid.UUID, as_of: date | None` | — | `VendorExposureRead` | `get_vendor_exposure_detail` | frontend/src/pages/VendorDetail.tsx | SOURCE-VERIFIED | BLOCKED_ENVIRONMENT |
| GET | `/ap-priority/vendors` | `INVOICE_READ` | `as_of: date | None, search: str | None` | pagination | `PaginatedResponse[VendorExposureRead]` | `list_vendor_exposure` | frontend/src/pages/Payables.jsx | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/approval-requests` | `APPROVAL_REQUEST_READ` | `agent_type: str | None, offset: int, limit: int` | — | `list[ApprovalRequestRead]` | `list_pending_approvals` | frontend/src/pages/Approvals.jsx, frontend/src/pages/Dashboard.jsx | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/approval-requests/{approval_request_id}/approve` | `APPROVAL_REQUEST_ACTION` | `approval_request_id: uuid.UUID, payload: ApproveRequest` | — | `ApprovalRequestRead` | `approve_request` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/approval-requests/{approval_request_id}/execute` | `APPROVAL_REQUEST_ACTION` | `approval_request_id: uuid.UUID` + optional `Idempotency-Key` header | — | `ApprovalRequestRead` incl. stable idempotency key + execution state | `execute_approved_request` | `Approvals.jsx` | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/approval-requests/{approval_request_id}/reject` | `APPROVAL_REQUEST_ACTION` | `approval_request_id: uuid.UUID, payload: RejectRequest` | — | `ApprovalRequestRead` | `reject_request` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| GET | `/ar-invoices` | `AR_INVOICE_READ` | `status_filter: ARInvoiceStatus` | — | `list[ARInvoiceRead]` | `list_ar_invoices_by_status` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/ar-invoices` | `AR_INVOICE_CREATE` | `payload: ARInvoiceCreate` | — | `ARInvoiceRead` | `ingest_ar_invoice` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/ar-invoices/{invoice_id}` | `AR_INVOICE_READ` | `invoice_id: uuid.UUID` | — | `ARInvoiceRead` | `get_ar_invoice` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/ar-invoices/{invoice_id}/send` | `AR_INVOICE_CREATE` | `invoice_id: uuid.UUID` | — | `ARInvoiceRead` | `send_ar_invoice` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| GET | `/audit/logs` | `AUDIT_LOG_READ` | `actor_id: str | None, action: str | None, resource_type: str | None, resource_id: str | None, outcome: str | None` | pagination | `PaginatedResponse[AuditLogRead]` | `list_audit_logs` | frontend/src/pages/Audit.jsx | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| GET | `/audit/verify` | `AUDIT_LOG_READ` | `—` | — | `AuditLogVerifyRead` | `verify_audit_chain` | frontend/src/pages/Audit.jsx | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/auth/login` | `public` | `payload: LoginRequest` | — | `TokenResponse` | `login` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/auth/logout` | `public` | `payload: RefreshRequest` | — | `LogoutResponse` | `logout` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/auth/me` | `authenticated` | `—` | — | `UserRead` | `me` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/auth/refresh` | `public` | `payload: RefreshRequest` | — | `TokenResponse` | `refresh` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/auth/register` | `public` | `payload: UserCreate` | — | `UserRead` | `register` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/bank-reconciliation/statement-lines` | `BANK_STATEMENT_INGEST` | `payload: IngestStatementLinesRequest` | — | `list[BankStatementLineRead]` | `ingest_statement_lines` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/bank-reconciliation/statement-lines/{statement_line_id}` | `BANK_STATEMENT_READ` | `statement_line_id: uuid.UUID` | — | `BankStatementLineRead` | `get_statement_line` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/bank-reconciliation/statement-lines/{statement_line_id}/confirm-match` | `BANK_STATEMENT_MATCH` | `statement_line_id: uuid.UUID, payload: ConfirmMatchRequest` | — | `BankStatementLineRead` | `confirm_match` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/budgets` | `BUDGET_MANAGE` | `payload: BudgetCreate` | — | `BudgetRead` | `create_budget` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/budgets/{budget_id}` | `BUDGET_READ` | `budget_id: uuid.UUID` | — | `BudgetRead` | `get_budget` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/credit-memos/ap` | `CREDIT_MEMO_CREATE` | `payload: APCreditMemoCreate` | — | `APCreditMemoRead` | `issue_ap_credit_memo` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| GET | `/credit-memos/ap/{credit_memo_id}` | `CREDIT_MEMO_READ` | `credit_memo_id: uuid.UUID` | — | `APCreditMemoRead` | `get_ap_credit_memo` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/credit-memos/ap/{credit_memo_id}/apply` | `CREDIT_MEMO_APPROVE` | `credit_memo_id: uuid.UUID` | — | `APCreditMemoRead` | `apply_ap_credit_memo` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/credit-memos/ar` | `CREDIT_MEMO_CREATE` | `payload: ARCreditMemoCreate` | — | `ARCreditMemoRead` | `issue_ar_credit_memo` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/credit-memos/ar/{credit_memo_id}` | `CREDIT_MEMO_READ` | `credit_memo_id: uuid.UUID` | — | `ARCreditMemoRead` | `get_ar_credit_memo` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/credit-memos/ar/{credit_memo_id}/apply` | `CREDIT_MEMO_APPROVE` | `credit_memo_id: uuid.UUID` | — | `ARCreditMemoRead` | `apply_ar_credit_memo` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| GET | `/customers` | `CUSTOMER_READ` | `—` | pagination | `PaginatedResponse[CustomerRead]` | `list_customers` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/customers` | `CUSTOMER_CREATE` | `payload: CustomerCreate` | — | `CustomerRead` | `create_customer` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/customers/{customer_id}` | `CUSTOMER_READ` | `customer_id: uuid.UUID` | — | `CustomerRead` | `get_customer` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| PATCH | `/customers/{customer_id}` | `CUSTOMER_MANAGE` | `customer_id: uuid.UUID, payload: CustomerUpdate` | — | `CustomerRead` | `update_customer` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/customers/{customer_id}/activate` | `CUSTOMER_MANAGE` | `customer_id: uuid.UUID` | — | `CustomerRead` | `activate_customer` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/fbr-remittances` | `FBR_REMITTANCE_RECORD` | `payload: FBRRemittanceCreate` | — | `FBRRemittanceRead` | `record_remittance` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/goods-receipts` | `GOODS_RECEIPT_CREATE` | `payload: GoodsReceiptCreate` | — | `GoodsReceiptRead` | `create_goods_receipt` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/health/live` | `public` | `—` | — | `dict` | `liveness` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| GET | `/health/ready` | `public` | `—` | — | `dict` | `readiness` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/incoming-payments` | `PAYMENT_INITIATE` | `payload: IncomingPaymentCreate` | — | `IncomingPaymentRead` | `record_incoming_payment` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/invoices` | `INVOICE_READ` | `status_filter: InvoiceStatus` | — | `list[InvoiceRead]` | `list_invoices_by_status` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/invoices` | `INVOICE_CREATE` | `payload: InvoiceCreate` | — | `InvoiceRead` | `ingest_invoice` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/invoices/{invoice_id}` | `INVOICE_READ` | `invoice_id: uuid.UUID` | — | `InvoiceRead` | `get_invoice` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/invoices/{invoice_id}/approve` | `INVOICE_APPROVE` | `invoice_id: uuid.UUID` | — | `InvoiceRead` | `approve_invoice` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/invoices/{invoice_id}/reject` | `INVOICE_APPROVE` | `invoice_id: uuid.UUID, payload: RejectInvoiceRequest` | — | `InvoiceRead` | `reject_invoice` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/payments` | `PAYMENT_INITIATE` | `payload: PaymentCreate` | — | `PaymentRead` | `schedule_payment` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/payments/{payment_id}/execute` | `PAYMENT_APPROVE` | `payment_id: uuid.UUID` | — | `PaymentRead` | `execute_payment` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/period-close` | `PERIOD_CLOSE_EXECUTE` | `payload: ClosePeriodRequest` | — | `PeriodCloseRead` | `close_period` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/period-close/{period_close_id}/reopen` | `PERIOD_CLOSE_EXECUTE` | `period_close_id: uuid.UUID, payload: ReopenPeriodRequest` | — | `PeriodCloseRead` | `reopen_period` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/purchase-orders` | `PURCHASE_ORDER_CREATE` | `payload: PurchaseOrderCreate` | — | `PurchaseOrderRead` | `create_purchase_order` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/purchase-orders/by-vendor/{vendor_id}` | `PURCHASE_ORDER_READ` | `vendor_id: uuid.UUID` | — | `list[PurchaseOrderRead]` | `list_purchase_orders_by_vendor` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| GET | `/purchase-orders/{purchase_order_id}` | `PURCHASE_ORDER_READ` | `purchase_order_id: uuid.UUID` | — | `PurchaseOrderRead` | `get_purchase_order` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| GET | `/reports/balance-sheet` | `REPORT_VIEW` | `as_of: date` | — | `BalanceSheetRead` | `get_balance_sheet` | frontend/src/pages/Reports.jsx | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/reports/profit-and-loss` | `REPORT_VIEW` | `start_date: date, end_date: date` | — | `ProfitAndLossRead` | `get_profit_and_loss` | frontend/src/pages/Reports.jsx | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/reports/trial-balance` | `REPORT_VIEW` | `as_of: date` | — | `TrialBalanceRead` | `get_trial_balance` | frontend/src/pages/Reports.jsx | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/sap/status` | `AGENT_INVOKE` | `—` | — | `SAPStatusRead` | `sap_status` | frontend/src/pages/SapIntegration.jsx | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/sap/verify` | `AGENT_INVOKE` | Empty JSON object | — | `SAPVerificationRead` | `verify_sap_read_only` | frontend/src/pages/SapIntegration.jsx | Implemented; mock test module skipped here due missing tenacity | BLOCKED_EXTERNAL_SAP |
| GET | `/tax-codes` | `TAX_CODE_READ` | `—` | — | `list[TaxCodeRead]` | `list_active_tax_codes` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/tax-codes` | `TAX_CODE_MANAGE` | `payload: TaxCodeCreate` | — | `TaxCodeRead` | `create_tax_code` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/tax-codes/calculate` | `TAX_CODE_READ` | `payload: TaxCalculationRequest` | — | `TaxCalculationResultRead` | `calculate_tax` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| GET | `/vendors` | `VENDOR_READ` | `—` | pagination | `PaginatedResponse[VendorRead]` | `list_vendors` | — | DIRECT | BLOCKED_ENVIRONMENT |
| POST | `/vendors` | `VENDOR_CREATE` | `payload: VendorCreate` | — | `VendorRead` | `create_vendor` | — | DIRECT | BLOCKED_ENVIRONMENT |
| GET | `/vendors/{vendor_id}` | `VENDOR_READ` | `vendor_id: uuid.UUID` | — | `VendorRead` | `get_vendor` | frontend/src/pages/VendorDetail.tsx | SOURCE-VERIFIED | BLOCKED_ENVIRONMENT |
| PATCH | `/vendors/{vendor_id}` | `VENDOR_MANAGE` | `vendor_id: uuid.UUID, payload: VendorUpdate` | — | `VendorRead` | `update_vendor` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/vendors/{vendor_id}/activate` | `VENDOR_MANAGE` | `vendor_id: uuid.UUID` | — | `VendorRead` | `activate_vendor` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |
| POST | `/vendors/{vendor_id}/risk-assessment` | `VENDOR_MANAGE` | `vendor_id: uuid.UUID, payload: VendorRiskAssessmentRequest` | — | `VendorRead` | `apply_vendor_risk_assessment` | — | INDIRECT / not route-mapped | BLOCKED_ENVIRONMENT |

## Pass 2 changes (2026-10-14)

All changes are additive. Existing requests keep working, with the one intentional exception marked below.

| Method and path | Change | Compatibility |
|---|---|---|
| `GET /reports/currencies` | New. Returns `{ "currencies": [...] }` of currencies with posted entries. Needs `report:view`. | new |
| `GET /reports/trial-balance`, `/profit-and-loss`, `/balance-sheet` | Optional `currency` (three letters). Responses add `currency` and `available_currencies`. | **Behaviour change:** with posted entries in more than one currency and no `currency`, the response is 422 with `details.available_currencies`. Previously the currencies were summed. |
| `GET /approval-requests` | Optional `view`: `pending` (default, unchanged), `awaiting_execution`, `executing`, `failed`, `executed`, `rejected`, `approved`, `all`. | compatible |
| `GET /approval-requests/summary` | New. `{ pending, awaiting_execution, executing, failed }`. Needs `approval_request:read`. | new |
| Error bodies | 422 adds `error_code`, `message`, `details.errors`, `correlation_id` and keeps `detail`. Other error bodies gain `correlation_id`. | compatible |
| `POST /approval-requests/{id}/execute` | `execution_error` is now a generic message for non business failures. | compatible |
