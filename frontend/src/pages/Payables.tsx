import { useEffect, useState, type ReactElement } from 'react'
import { api } from '../api'
import { PipelineBar } from '../components/charts'
import { Icon } from '../components/Icons'
import {
  ApiErrorBanner, Card, CurrencyChips, DataTable, EmptyState, Field, KpiCard, Notice, PageHeader, Pagination, RISK_TONES,
  SectionHeading, Skeleton, SkeletonKpis, StatusBadge, Tabs,
} from '../components/ui'
import { currencyAmountItems, formatDate, formatLabel, formatMoney, formatNumber } from '../formatters'
import { useAsync, useDebouncedValue } from '../hooks'
import type { ApSummary, Paginated, PaymentObligation, VendorExposure } from '../types'
import type { PipelineSegment } from '../chartData'

const PAGE_SIZE = 25
const STATUSES = ['blocked', 'payment_failed', 'awaiting_approval', 'ready_to_schedule', 'scheduled', 'executed']
const STATUS_TONES: Record<string, string> = { blocked: 'rose', payment_failed: 'rose', awaiting_approval: 'amber', ready_to_schedule: 'blue', scheduled: 'violet', executed: 'green' }

export default function Payables({ onVendor }: { onVendor: (id: string) => void }): ReactElement {
  const [tab, setTab] = useState('summary')
  const [searchInput, setSearchInput] = useState('')
  const search = useDebouncedValue(searchInput.trim(), 300)
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [page, setPage] = useState(1)

  useEffect(() => { setPage(1) }, [search, status, priority, tab])

  const summary = useAsync((signal) => api.get<ApSummary>('/ap-priority/summary', undefined, signal), [])
  const obligations = useAsync(
    (signal) => (tab === 'obligations'
      ? api.get<Paginated<PaymentObligation>>('/ap-priority/obligations', { page, page_size: PAGE_SIZE, search: search || undefined, status: status || undefined, priority: priority || undefined, include_executed: status === 'executed' ? true : undefined }, signal)
      : Promise.resolve(null)),
    [tab, page, search, status, priority],
  )
  const vendors = useAsync(
    (signal) => (tab === 'vendors'
      ? api.get<Paginated<VendorExposure>>('/ap-priority/vendors', { page, page_size: PAGE_SIZE, search: search || undefined }, signal)
      : Promise.resolve(null)),
    [tab, page, search],
  )

  function changeTab(next: string): void {
    setTab(next)
    setSearchInput('')
    setStatus('')
    setPriority('')
  }

  const refresh = () => { summary.reload(); obligations.reload(); vendors.reload() }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Accounts payable"
        title="Payables"
        description="Payment obligations, vendor exposure, and urgency signals from the backend AP priority service. Each currency is shown on its own."
        action={<button type="button" className="icon-button" onClick={refresh} aria-label="Refresh payables" title="Refresh payables"><Icon name="refresh" size={17} /></button>}
      />
      {summary.error && <ApiErrorBanner error={summary.error} title="Payables summary could not be loaded" onRetry={summary.reload} />}
      {!summary.data && !summary.error && <SkeletonKpis count={3} />}
      {summary.data && (
        <div className="kpi-grid three">
          <KpiCard label="Total payable" value={<CurrencyChips items={currencyAmountItems(summary.data.currency_balances, 'total_payable')} />} caption={`${formatNumber(summary.data.open_obligation_count)} open obligations`} icon="wallet" tone="blue" />
          <KpiCard label="Overdue amount" value={<CurrencyChips items={currencyAmountItems(summary.data.currency_balances, 'overdue_amount')} />} caption={`${formatNumber(summary.data.overdue_count)} overdue obligations`} icon="alert" tone="amber" />
          <KpiCard label="Executed in the last 30 days" value={<CurrencyChips items={currencyAmountItems(summary.data.currency_balances, 'executed_last_30_days_amount')} />} caption={`${formatNumber(summary.data.executed_last_30_days_count ?? 0)} payments`} icon="check" tone="green" />
        </div>
      )}

      <Tabs label="Payables views" items={[{ key: 'summary', label: 'Summary' }, { key: 'obligations', label: 'Obligations' }, { key: 'vendors', label: 'Vendor exposure' }]} value={tab} onChange={changeTab} />

      {tab === 'summary' && summary.data && (
        <div className="dashboard-grid">
          <Card>
            <SectionHeading title="Open obligations by status" description="Counts and amounts are computed by the backend, per currency." />
            {summary.data.currency_balances.length === 0
              ? <EmptyState title="No open obligations" description="There are no open payment obligations with a reportable currency." />
              : <div className="chart-stack">{summary.data.currency_balances.map((balance) => {
                const segments: PipelineSegment[] = STATUSES.map((key) => ({ key, label: formatLabel(key), tone: STATUS_TONES[key] ?? 'blue', value: balance.by_status_count?.[key] ?? 0 }))
                return (
                  <div key={balance.currency}>
                    <div className="chart-currency">{balance.currency}</div>
                    <PipelineBar label={`${balance.currency} obligations by status`} segments={segments} />
                    <div className="exposure-list">
                      {Object.entries(balance.by_status_amount ?? {}).map(([key, amount]) => (
                        <div className="exposure-line" key={key}><span>{formatLabel(key)}</span><strong>{formatMoney(amount, balance.currency)}</strong><em>{balance.by_status_count?.[key] ?? 0}</em></div>
                      ))}
                    </div>
                  </div>
                )
              })}</div>}
          </Card>
          <Card>
            <SectionHeading title="Payment health" />
            <div className="signal-grid">
              <div><span>Open obligations</span><strong>{formatNumber(summary.data.open_obligation_count)}</strong></div>
              <div><span>Overdue count</span><strong>{formatNumber(summary.data.overdue_count)}</strong></div>
              <div><span>Paid, last 30 days</span><strong>{formatNumber(summary.data.executed_last_30_days_count ?? 0)}</strong></div>
            </div>
            <Notice tone="warning" icon="alert" live="none">Payment prioritization is read only here. Failed obligations are surfaced, but retry and reschedule are intentionally not available.</Notice>
          </Card>
        </div>
      )}

      {(tab === 'obligations' || tab === 'vendors') && (
        <Card>
          <div className="filter-bar">
            <Field label={tab === 'vendors' ? 'Search vendor' : 'Search invoice or vendor'}>
              <div className="input-with-icon"><Icon name="search" size={16} /><input type="search" value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder={tab === 'vendors' ? 'Vendor name' : 'Invoice number or vendor'} /></div>
            </Field>
            {tab === 'obligations' && <>
              <Field label="Status">
                <select value={status} onChange={(e) => setStatus(e.target.value)}>
                  <option value="">All statuses</option>
                  {STATUSES.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
                </select>
              </Field>
              <Field label="Priority">
                <select value={priority} onChange={(e) => setPriority(e.target.value)}>
                  <option value="">All priorities</option>
                  {['low', 'medium', 'high', 'critical'].map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
                </select>
              </Field>
            </>}
          </div>

          {tab === 'obligations' && (obligations.error
            ? <ApiErrorBanner error={obligations.error} title="Obligations could not be loaded" onRetry={obligations.reload} />
            : !obligations.data ? <Skeleton lines={5} label="Loading payment obligations" />
            : <>
              <DataTable<PaymentObligation>
                ariaLabel="Payment obligations"
                rows={obligations.data.items}
                rowKey={(row) => row.invoice_id}
                columns={[
                  { key: 'vendor_name', label: 'Vendor', render: (row) => <strong>{row.vendor_name}</strong> },
                  { key: 'invoice_number', label: 'Invoice' },
                  { key: 'amount', label: 'Amount', numeric: true, render: (row) => formatMoney(row.amount, row.currency) },
                  { key: 'due_date', label: 'Due', render: (row) => formatDate(row.due_date) },
                  { key: 'timing', label: 'Timing', render: (row) => (row.days_until_due < 0 ? <span className="danger-number">{Math.abs(row.days_until_due)}d overdue</span> : row.days_until_due === 0 ? 'Due today' : `${row.days_until_due}d`) },
                  { key: 'status', label: 'Status', render: (row) => <StatusBadge value={row.status} toneMap={STATUS_TONES} /> },
                  { key: 'priority', label: 'Priority', render: (row) => (row.priority ? <StatusBadge value={row.priority} toneMap={RISK_TONES} /> : '—') },
                ]}
              />
              <Pagination page={obligations.data.page} pageSize={obligations.data.page_size} total={obligations.data.total} onPage={setPage} busy={obligations.loading} />
            </>)}

          {tab === 'vendors' && (vendors.error
            ? <ApiErrorBanner error={vendors.error} title="Vendor exposure could not be loaded" onRetry={vendors.reload} />
            : !vendors.data ? <Skeleton lines={5} label="Loading vendor exposure" />
            : <>
              <DataTable<VendorExposure>
                ariaLabel="Vendor exposure"
                rows={vendors.data.items}
                rowKey={(row) => row.vendor_id}
                columns={[
                  { key: 'vendor_name', label: 'Vendor', render: (row) => <button type="button" className="link-button" onClick={() => onVendor(row.vendor_id)}>{row.vendor_name}<Icon name="chevron" size={14} /></button> },
                  { key: 'total_exposure', label: 'Exposure', render: (row) => <CurrencyChips items={currencyAmountItems(row.currency_balances, 'total_exposure')} /> },
                  { key: 'overdue_amount', label: 'Overdue', render: (row) => <CurrencyChips items={currencyAmountItems(row.currency_balances, 'overdue_amount')} /> },
                  { key: 'open_invoice_count', label: 'Open invoices', numeric: true, render: (row) => formatNumber(row.open_invoice_count) },
                  { key: 'payment_failed_count', label: 'Failed payments', numeric: true, render: (row) => (row.payment_failed_count > 0 ? <span className="danger-number">{formatNumber(row.payment_failed_count)}</span> : '0') },
                  { key: 'highest_priority', label: 'Highest priority', render: (row) => <StatusBadge value={row.highest_priority} toneMap={RISK_TONES} /> },
                ]}
              />
              <Pagination page={vendors.data.page} pageSize={vendors.data.page_size} total={vendors.data.total} onPage={setPage} busy={vendors.loading} />
            </>)}
        </Card>
      )}
    </div>
  )
}
