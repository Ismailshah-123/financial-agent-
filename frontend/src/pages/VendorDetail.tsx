import { useEffect, useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icons'
import {
  Card,
  DataTable,
  EmptyState,
  KpiCard,
  LoadingPanel,
  PageHeader,
  SectionHeading,
  StatusBadge,
} from '../components/ui'
import { formatCurrencyAmounts, formatDate, formatLabel, formatMoney, formatNumber } from '../formatters'

type VendorRead = {
  id: string
  name: string
  tax_id: string | null
  email: string | null
  phone: string | null
  address_line: string | null
  bank_account_iban: string | null
  bank_account_swift: string | null
  default_currency: string
  payment_terms_days: number
  approval_limit: string | number | null
  is_1099_vendor: boolean
  filer_status: string | null
  status: string
  risk_rating: number | null
  sap_business_partner_code: string | null
}

type VendorExposure = {
  vendor_id: string
  vendor_name: string
  currency: string | null
  total_exposure: string | number | null
  open_invoice_count: number
  overdue_amount: string | number | null
  overdue_invoice_count: number
  blocked_count: number
  payment_failed_count: number
  awaiting_approval_count: number
  highest_priority: string
  currency_balances: Array<{currency:string;total_exposure:string|number;overdue_amount:string|number;open_invoice_count:number;overdue_invoice_count:number;blocked_count:number;payment_failed_count:number;awaiting_approval_count:number;highest_priority:string}>
}

type PaymentObligation = {
  invoice_id: string
  invoice_number: string
  vendor_id: string
  vendor_name: string
  amount: string | number
  currency: string
  due_date: string
  days_until_due: number
  status: string
  priority_score: number | null
  priority: string | null
  reason: string
  scheduled_date: string | null
  executed_date: string | null
}

type Paginated<T> = { items: T[]; total: number; page: number; page_size: number }
type DetailProps = { id: string; onBack: () => void; can: (permission: string) => boolean }

export default function VendorDetail({ id, onBack, can }: DetailProps) {
  const mayReadVendor = can('vendor:read')
  const mayReadBankDetails = can('vendor:bank_details:read')
  const [vendor, setVendor] = useState<VendorRead | null>(null)
  const [exposure, setExposure] = useState<VendorExposure | null>(null)
  const [obligations, setObligations] = useState<Paginated<PaymentObligation> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [partialWarning, setPartialWarning] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    setPartialWarning('')
    setVendor(null)
    setExposure(null)
    setObligations(null)

    const requests: Promise<unknown>[] = [
      api.get<VendorExposure>(`/ap-priority/vendor/${id}`),
      api.get<Paginated<PaymentObligation>>('/ap-priority/obligations', {
        vendor_id: id,
        page: 1,
        page_size: 25,
        include_executed: true,
      }),
    ]
    if (mayReadVendor) requests.push(api.get<VendorRead>(`/vendors/${id}`))

    Promise.allSettled(requests)
      .then((results) => {
        if (!active) return
        const exposureResult = results[0]
        const obligationsResult = results[1]
        const vendorResult = mayReadVendor ? results[2] : undefined

        if (exposureResult.status === 'fulfilled') {
          setExposure(exposureResult.value as VendorExposure)
        } else {
          setError('Vendor exposure could not be loaded. Check your permission and the API connection, then retry.')
        }
        if (obligationsResult.status === 'fulfilled') {
          setObligations(obligationsResult.value as Paginated<PaymentObligation>)
        } else {
          setPartialWarning('The vendor summary is available, but invoice-level obligations could not be loaded.')
        }
        if (vendorResult?.status === 'fulfilled') {
          setVendor(vendorResult.value as VendorRead)
        } else if (mayReadVendor && vendorResult?.status === 'rejected') {
          setPartialWarning((current) => [current, 'Vendor profile details could not be loaded.'].filter(Boolean).join(' '))
        }
      })
      .catch(() => {
        if (active) setError('Vendor detail could not be loaded. Please retry.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => { active = false }
  }, [id, mayReadVendor])

  if (loading) return <LoadingPanel label="Loading vendor profile and exposure…" />

  if (error && !exposure) {
    return (
      <div className="page-stack">
        <button className="back-link" onClick={onBack}><Icon name="chevron" size={14} /> Back to payables</button>
        <PageHeader eyebrow="Accounts payable" title="Vendor detail" description="Exposure and obligation records from the finance API." />
        <div className="error-banner"><div><strong>Vendor details unavailable</strong><span>{error}</span></div><button className="button button-secondary" onClick={() => window.location.reload()}>Retry</button></div>
      </div>
    )
  }

  const title = vendor?.name || exposure?.vendor_name || 'Vendor detail'
  const currency = exposure?.currency || vendor?.default_currency || null

  return (
    <div className="page-stack">
      <button className="back-link" onClick={onBack}><Icon name="chevron" size={14} /> Back to payables</button>
      <PageHeader
        eyebrow="Vendor intelligence"
        title={title}
        description="Vendor identity, exposure, payment obligations, and rule-based risk signals returned by the backend."
      />
      {error && <div className="error-banner"><div><strong>Some vendor data is unavailable</strong><span>{error}</span></div></div>}
      {partialWarning && <div className="callout warning"><Icon name="alert" size={16} /><span>{partialWarning}</span></div>}

      {exposure && <div className="kpi-grid">
        <KpiCard label="Total exposure" value={formatCurrencyAmounts(exposure.currency_balances, 'total_exposure', exposure.total_exposure, currency)} caption={`${formatNumber(exposure.open_invoice_count)} open obligations`} icon="wallet" tone="blue" />
        <KpiCard label="Overdue exposure" value={formatCurrencyAmounts(exposure.currency_balances, 'overdue_amount', exposure.overdue_amount, currency)} caption={`${formatNumber(exposure.overdue_invoice_count)} overdue obligations`} icon="alert" tone="amber" />
        <KpiCard label="Payment failures" value={formatNumber(exposure.payment_failed_count)} caption="Backend-reported failed obligations" icon="alert" tone="rose" />
        <KpiCard label="Highest priority" value={formatLabel(exposure.highest_priority)} caption={`${formatNumber(exposure.awaiting_approval_count)} awaiting approval`} icon="chart" tone="violet" />
      </div>}

      <div className="dashboard-grid">
        <Card>
          <SectionHeading title="Vendor profile" description="Source: vendor API. Bank coordinates are returned only to roles with explicit bank-details permission." />
          {vendor ? <div className="profile-grid">
            <div><span>Vendor status</span><strong><StatusBadge value={vendor.status} toneMap={{ active: 'green', approved: 'green', pending_review: 'amber', blocked: 'rose', inactive: 'neutral' }} /></strong></div>
            <div><span>Risk rating</span><strong>{vendor.risk_rating === null ? 'Not assessed' : `${vendor.risk_rating}/100`}</strong></div>
            <div><span>Tax ID</span><strong>{vendor.tax_id || 'Not provided'}</strong></div>
            <div><span>Currency</span><strong>{vendor.default_currency || '—'}</strong></div>
            <div><span>Email</span><strong>{vendor.email || 'Not provided'}</strong></div>
            <div><span>Phone</span><strong>{vendor.phone || 'Not provided'}</strong></div>
            <div><span>Payment terms</span><strong>{formatNumber(vendor.payment_terms_days)} days</strong></div>
            <div><span>Approval limit</span><strong>{vendor.approval_limit === null ? 'Not configured' : formatMoney(vendor.approval_limit, currency || vendor.default_currency)}</strong></div>
            <div><span>Tax filer status</span><strong>{formatLabel(vendor.filer_status)}</strong></div>
            <div><span>SAP Business Partner</span><strong>{vendor.sap_business_partner_code || 'Not linked'}</strong></div>
            <div className="vendor-profile-wide"><span>Address</span><strong>{vendor.address_line || 'Not provided'}</strong></div>
            {mayReadBankDetails && <>
              <div className="vendor-profile-wide"><span>Bank IBAN</span><strong>{vendor.bank_account_iban || 'Not provided'}</strong></div>
              <div><span>Bank SWIFT/BIC</span><strong>{vendor.bank_account_swift || 'Not provided'}</strong></div>
            </>}
          </div> : <EmptyState title={mayReadVendor ? 'Vendor profile unavailable' : 'Profile permission not granted'} description={mayReadVendor ? 'The vendor API did not return a profile. Exposure remains available from the AP priority service.' : 'Your role can view payables exposure but does not have permission to read full vendor profile fields.'} />}
          {!mayReadBankDetails && vendor && <div className="callout info"><Icon name="lock" size={15} /><span>Bank coordinates are hidden because this role does not have vendor bank-details read permission.</span></div>}
        </Card>

        <Card>
          <SectionHeading title="Rule-based payment assessment" description="Deterministic exposure signals; no LLM risk score is inferred by the frontend." />
          {exposure ? <div className="fact-list">
            <div><span>Highest payment priority</span><strong><StatusBadge value={exposure.highest_priority} toneMap={{ low: 'green', medium: 'blue', high: 'amber', critical: 'rose' }} /></strong></div>
            <div><span>Blocked obligations</span><strong>{formatNumber(exposure.blocked_count)}</strong></div>
            <div><span>Awaiting approval</span><strong>{formatNumber(exposure.awaiting_approval_count)}</strong></div>
            <div><span>Failed payment obligations</span><strong>{formatNumber(exposure.payment_failed_count)}</strong></div>
            <div><span>Overdue invoice count</span><strong>{formatNumber(exposure.overdue_invoice_count)}</strong></div>
          </div> : <EmptyState title="No exposure assessment" description="The backend did not return vendor exposure." />}
          <div className="callout warning"><Icon name="alert" size={16} /><span>This screen is read-only. It does not retry failed payments, change bank details, or post documents to SAP.</span></div>
        </Card>
      </div>

      <Card>
        <SectionHeading title="Open obligations and recent executions" description="Invoice and payment states are returned by the AP priority service. Amounts and urgency are not recalculated in React." />
        {!obligations ? <EmptyState title="Obligation details unavailable" description="No invoice-level result was returned for this vendor." /> : obligations.items.length === 0 ? <EmptyState title="No obligations found" description="The backend returned no open or recently executed obligations for this vendor." /> : <DataTable
          rows={obligations.items}
          rowKey={(row: PaymentObligation) => row.invoice_id}
          columns={[
            { key: 'invoice_number', label: 'Invoice', render: (row: PaymentObligation) => <strong>{row.invoice_number}</strong> },
            { key: 'amount', label: 'Amount', render: (row: PaymentObligation) => formatMoney(row.amount, row.currency) },
            { key: 'due_date', label: 'Due date', render: (row: PaymentObligation) => formatDate(row.due_date) },
            { key: 'timing', label: 'Timing', render: (row: PaymentObligation) => row.days_until_due < 0 ? <span className="danger-number">{Math.abs(row.days_until_due)} days overdue</span> : `${row.days_until_due} days` },
            { key: 'status', label: 'Status', render: (row: PaymentObligation) => <StatusBadge value={row.status} toneMap={{ open: 'blue', overdue: 'amber', scheduled: 'violet', executed: 'green', blocked: 'rose', payment_failed: 'rose' }} /> },
            { key: 'priority', label: 'Priority', render: (row: PaymentObligation) => row.priority ? <StatusBadge value={row.priority} toneMap={{ low: 'green', medium: 'blue', high: 'amber', critical: 'rose' }} /> : '—' },
            { key: 'execution_date', label: 'Executed', render: (row: PaymentObligation) => formatDate(row.executed_date) },
          ]}
        />}
        {obligations && obligations.total > obligations.items.length && <p className="muted-label">Showing {obligations.items.length} of {formatNumber(obligations.total)} records. Use the Payables workspace for filtering and pagination.</p>}
      </Card>
    </div>
  )
}
