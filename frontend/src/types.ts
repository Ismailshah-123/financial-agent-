/**
 * Shared contract types. They mirror the FastAPI response schemas in
 * `app/schemas/*`. Monetary amounts are serialised by the backend as decimal
 * strings and are kept as `string` here: the browser never does arithmetic on
 * them, it only formats them (see `formatters.ts`).
 */

export type Permission = string

export interface User {
  id: string
  email: string
  full_name: string
  role: string
  is_active: boolean
  permissions: Permission[]
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface ApiErrorLike {
  message: string
  status?: number
  correlationId?: string | null
}

/** Decimal amount as serialised by the API (never a JS float). */
export type Money = string

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'

// ---------------------------------------------------------------- approvals
export type ApprovalView =
  | 'pending'
  | 'awaiting_execution'
  | 'executing'
  | 'failed'
  | 'executed'
  | 'rejected'
  | 'approved'
  | 'all'

export interface ApprovalSummary {
  pending: number
  awaiting_execution: number
  executing: number
  failed: number
}

export interface FinancialImpact {
  amount: Money
  currency: string
}

export interface AgentEvidence {
  document_type: string
  document_id: string
}

export interface AgentDecisionPayload {
  reasoning?: string
  confidence?: { value: number | string } | null
  financial_impact?: FinancialImpact | null
  supporting_evidence?: AgentEvidence[]
  relevant_policies?: string[]
  rollback_strategy?: { is_reversible?: boolean } | null
  requires_approval?: boolean
}

export interface ApprovalRequest {
  id: string
  decision_id: string
  agent_type: string
  correlation_id: string
  actor_id: string
  risk_level: RiskLevel | string
  summary: string
  decision: AgentDecisionPayload
  status: 'pending' | 'approved' | 'rejected' | string
  resolved_at: string | null
  resolved_by_id: string | null
  resolution_notes: string | null
  action_type: string | null
  action_payload: Record<string, unknown>
  idempotency_key: string | null
  execution_status: 'not_applicable' | 'execution_pending' | 'executing' | 'executed' | 'failed' | string
  execution_attempted_at: string | null
  executed_at: string | null
  execution_result: Record<string, unknown> | null
  execution_error: string | null
  created_at: string
}

// -------------------------------------------------------------------- audit
export interface AuditLogEntry {
  id: string
  sequence_number: number
  actor_id: string
  action: string
  resource_type: string
  resource_id: string
  outcome: 'success' | 'denied' | 'failed' | string
  correlation_id: string
  metadata: Record<string, unknown>
  prev_hash: string
  entry_hash: string
  created_at: string
}

export interface AuditVerification {
  valid: boolean
  checked_entries: number
  first_failure_sequence: number | null
  message: string
}

// ------------------------------------------------------------------ reports
export interface AccountBalanceLine {
  account_code: string
  account_name: string
  account_type: string
  total_debit: Money
  total_credit: Money
  balance: Money
}

interface ReportCurrencyFields {
  /** The single currency the report was produced in; null for an empty ledger window. */
  currency: string | null
  available_currencies: string[]
}

export interface TrialBalanceReport extends ReportCurrencyFields {
  as_of: string
  lines: AccountBalanceLine[]
  total_debit: Money
  total_credit: Money
  is_balanced: boolean
}

export interface ProfitAndLossReport extends ReportCurrencyFields {
  start_date: string
  end_date: string
  revenue_lines: AccountBalanceLine[]
  expense_lines: AccountBalanceLine[]
  total_revenue: Money
  total_expense: Money
  net_income: Money
}

export interface BalanceSheetReport extends ReportCurrencyFields {
  as_of: string
  asset_lines: AccountBalanceLine[]
  liability_lines: AccountBalanceLine[]
  equity_lines: AccountBalanceLine[]
  total_assets: Money
  total_liabilities: Money
  total_equity: Money
  computed_retained_earnings: Money
  is_balanced: boolean
}

export interface ReportCurrencies {
  currencies: string[]
}

// ---------------------------------------------------------------------- SAP
export interface SapStatus {
  enabled: boolean
  configured: boolean
  service_layer_url_configured: boolean
  company_db_configured: boolean
  credentials_configured: boolean
  verify_ssl: boolean
  live_connection_verified: boolean
  supported_entities: string[]
}

export type SapVerificationState =
  | 'disabled'
  | 'not_configured'
  | 'configuration_invalid'
  | 'connection_unreachable'
  | 'authentication_failed'
  | 'authenticated_and_reachable'
  | 'read_only_verification_failed'
  | 'read_only_verification_passed'

export interface SapVerification {
  state: SapVerificationState
  message: string
  checked_at: string
  verified_at: string | null
  probe_resource: string
  records_returned: number | null
  error_category: string | null
  correlation_id: string
}

// ---------------------------------------------------------------- dashboard
export interface CurrencyBalanceBase {
  currency: string
}

export interface AgingCurrencyBalance extends CurrencyBalanceBase {
  total_outstanding: Money
  overdue_amount: Money
  current_amount: Money
  amount_1_30: Money
  amount_31_60: Money
  amount_61_90: Money
  amount_91_120: Money
  amount_121_plus: Money
  open_invoice_count: number
  overdue_invoice_count: number
  bucket_percentages?: Record<string, number>
}

export interface AgingSummary {
  as_of: string
  currency: string | null
  total_outstanding: Money | null
  overdue_amount: Money | null
  open_invoice_count: number
  overdue_invoice_count: number
  customer_count: number
  oldest_days_overdue: number
  currency_balances: AgingCurrencyBalance[]
}

export interface ApCurrencyBalance extends CurrencyBalanceBase {
  total_payable: Money
  overdue_amount: Money
  open_obligation_count?: number
  overdue_count?: number
  by_status_amount?: Record<string, Money>
  by_status_count?: Record<string, number>
  executed_last_30_days_amount?: Money
  executed_last_30_days_count?: number
}

export interface ApSummary {
  currency: string | null
  total_payable: Money | null
  overdue_amount: Money | null
  open_obligation_count: number
  overdue_count: number
  executed_last_30_days_amount?: Money | null
  executed_last_30_days_count?: number
  currency_balances: ApCurrencyBalance[]
}

export interface PaymentObligation {
  invoice_id: string
  invoice_number: string
  vendor_id: string
  vendor_name: string
  amount: Money
  currency: string
  due_date: string
  days_until_due: number
  status: string
  priority: string | null
  reason: string
}

export interface VendorExposure {
  vendor_id: string
  vendor_name: string
  currency: string | null
  open_invoice_count: number
  payment_failed_count: number
  highest_priority: string
  currency_balances: { currency: string; total_exposure: Money; overdue_amount: Money }[]
}

// ------------------------------------------------------------------- health
export interface HealthReady {
  status: string
  service: string
}

// ------------------------------------------------------------------- agents
export interface AgentDecisionView {
  decision_id?: string
  risk_level: string
  summary: string
  reasoning: string
  confidence?: { value: number | string } | null
  requires_approval?: boolean
  financial_impact?: FinancialImpact | null
  supporting_evidence?: AgentEvidence[]
}

export interface AgentRunResult {
  run_id: string
  status: string
  agent_type: string
  duration_ms?: number
  error_message?: string | null
  decisions?: AgentDecisionView[]
}

export interface AgentField {
  name: string
  label: string
  kind: 'text' | 'uuid' | 'number' | 'date' | 'select' | string
  required: boolean
  description?: string | null
  options: string[]
}

export interface AgentCatalogItem {
  key: string
  name: string
  description: string
  endpoint: string
  input_fields: AgentField[]
}

// ---------------------------------------------------------------- customers
export interface CustomerCurrencyBalance extends AgingCurrencyBalance {
  oldest_due_date: string | null
  oldest_days_overdue: number
  credit_limit: Money | null
  credit_utilization: Money | null
  priority_score: number
  risk: string
  priority: string
  priority_reasons: string[]
  recommended_action: string
}

export interface CustomerAging {
  customer_id: string
  customer_name: string
  currency: string | null
  as_of: string
  total_outstanding: Money | null
  overdue_amount: Money | null
  oldest_due_date: string | null
  oldest_days_overdue: number
  open_invoice_count: number
  overdue_invoice_count: number
  credit_utilization: Money | null
  priority_score: number
  risk: string
  priority: string
  priority_reasons: string[]
  recommended_action: string
  currency_balances: CustomerCurrencyBalance[]
}
