import { useEffect, useState, type ReactElement } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icons'
import {
  ApiErrorBanner, Card, CurrencyChips, DataTable, EmptyState, Field, KpiCard, LoadingPanel, Notice, PageHeader,
  Pagination, RISK_TONES, SectionHeading, StatusBadge, Tabs,
} from '../components/ui'
import { currencyAmountItems, formatDate, formatMoney, formatNumber, formatPercent } from '../formatters'
import { useAsync, useDebouncedValue } from '../hooks'
import type { AgingSummary, Paginated } from '../types'

const PAGE_SIZE = 25
const BUCKET_OPTIONS = ['current', '1-30', '31-60', '61-90', '91-120', '121+']
const BUCKET_ROWS: [string, string, string][] = [
  ['Current', 'current_amount', 'current'],
  ['1 to 30 days', 'amount_1_30', '1-30'],
  ['31 to 60 days', 'amount_31_60', '31-60'],
  ['61 to 90 days', 'amount_61_90', '61-90'],
  ['91 to 120 days', 'amount_91_120', '91-120'],
  ['121+ days', 'amount_121_plus', '121+'],
]
const BUCKET_TONES: Record<string, string> = { current: 'green', '1-30': 'blue', '31-60': 'blue', '61-90': 'amber', '91-120': 'amber', '121+': 'rose' }

interface CustomerRow {
  customer_id: string
  customer_name: string
  currency_balances: { currency: string; total_outstanding: string }[]
  oldest_days_overdue: number
  credit_utilization: string | number | null
  priority_score: number
  priority: string
}

interface InvoiceRow {
  invoice_id: string
  invoice_number: string
  customer_name: string
  invoice_date: string
  due_date: string
  amount_outstanding: string
  currency: string
  days_overdue: number
  bucket: string
}

export default function Receivables({ onCustomer }: { onCustomer: (id: string) => void }): ReactElement {
  const [tab, setTab] = useState('overview')
  const [searchInput, setSearchInput] = useState('')
  const search = useDebouncedValue(searchInput.trim(), 300)
  const [bucket, setBucket] = useState('')
  // Each list owns its page so paging customers never disturbs the invoice list (and vice versa).
  const [customerPage, setCustomerPage] = useState(1)
  const [invoicePage, setInvoicePage] = useState(1)

  useEffect(() => { setCustomerPage(1); setInvoicePage(1) }, [search])

  const summary = useAsync((signal) => api.get<AgingSummary>('/aging/summary', undefined, signal), [])
  const customers = useAsync(
    (signal) => (tab === 'customers'
      ? api.get<Paginated<CustomerRow>>('/aging/customers', { page: customerPage, page_size: PAGE_SIZE, search: search || undefined }, signal)
      : Promise.resolve(null)),
    [tab, customerPage, search],
  )
  const invoices = useAsync(
    (signal) => (tab === 'invoices'
      ? api.get<Paginated<InvoiceRow>>('/aging/invoices', { page: invoicePage, page_size: PAGE_SIZE, bucket: bucket || undefined, search: search || undefined }, signal)
      : Promise.resolve(null)),
    [tab, invoicePage, bucket, search],
  )

  const refresh = () => { summary.reload(); customers.reload(); invoices.reload() }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Accounts receivable"
        title="Receivables"
        description="Open invoices, aging pressure and customer collection priorities. Each currency is shown on its own; amounts in different currencies are never added together."
        action={<button type="button" className="icon-button" onClick={refresh} aria-label="Refresh receivables" title="Refresh receivables"><Icon name="refresh" size={17} /></button>}
      />
      {summary.error && <ApiErrorBanner error={summary.error} title="Receivables summary could not be loaded" onRetry={summary.reload} />}
      {summary.data && (
        <div className="kpi-grid">
          <KpiCard label="Open receivables" value={<CurrencyChips items={currencyAmountItems(summary.data.currency_balances, 'total_outstanding')} />} caption={`${summary.data.open_invoice_count} open invoices`} icon="users" tone="blue" />
          <KpiCard label="Overdue balance" value={<CurrencyChips items={currencyAmountItems(summary.data.currency_balances, 'overdue_amount')} />} caption={`${summary.data.overdue_invoice_count} overdue invoices`} icon="alert" tone="amber" />
          <KpiCard label="Customers with exposure" value={formatNumber(summary.data.customer_count)} caption={`Oldest is ${summary.data.oldest_days_overdue} days overdue`} icon="users" tone="violet" />
        </div>
      )}
      {!summary.data && !summary.error && <LoadingPanel label="Loading receivables…" />}

      <Tabs
        label="Receivables views"
        items={[{ key: 'overview', label: 'Aging overview' }, { key: 'customers', label: 'Customers' }, { key: 'invoices', label: 'Invoices' }]}
        value={tab}
        onChange={setTab}
      />

      {tab === 'overview' && summary.data && (
        <div className="dashboard-grid">
          <Card>
            <SectionHeading title="Aging distribution by currency" description={`Position as of ${formatDate(summary.data.as_of)}.`} />
            {summary.data.currency_balances.length === 0
              ? <EmptyState title="No open receivables" description="There are no positive outstanding AR invoices in the selected portfolio." />
              : summary.data.currency_balances.map((balance) => (
                <div className="aging-currency-group" key={balance.currency}>
                  <h3>{balance.currency}</h3>
                  {BUCKET_ROWS.map(([name, key, pctKey]) => {
                    const pct = Number(balance.bucket_percentages?.[pctKey] ?? 0)
                    return (
                      <div className="aging-detail" key={key}>
                        <div><strong>{name}</strong><span>{formatMoney((balance as unknown as Record<string, string>)[key], balance.currency)}</span></div>
                        <div className="bar" aria-hidden="true"><i style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} /></div>
                        <small>{pct.toFixed(1)}% of {balance.currency} open receivables</small>
                      </div>
                    )
                  })}
                </div>
              ))}
          </Card>
          <Card>
            <SectionHeading title="Collection context" description="Aging and priority are calculated by the backend." />
            <div className="signal-grid">
              <div><span>Open invoices</span><strong>{summary.data.open_invoice_count}</strong></div>
              <div><span>Overdue invoices</span><strong>{summary.data.overdue_invoice_count}</strong></div>
              <div><span>Customers</span><strong>{summary.data.customer_count}</strong></div>
              <div><span>Oldest overdue</span><strong>{summary.data.oldest_days_overdue}d</strong></div>
            </div>
            <Notice tone="info" icon="bot" live="none">Collection recommendations come from the backend. This screen does not recompute risk.</Notice>
          </Card>
        </div>
      )}

      {tab !== 'overview' && (
        <Card>
          <SectionHeading
            title={tab === 'customers' ? 'Customer exposure' : 'Invoice level aging'}
            description={tab === 'customers' ? 'Search customers by name.' : 'Filter open AR invoices by customer, invoice number and aging bucket.'}
          />
          <div className="filter-bar">
            <Field label="Search">
              <div className="input-with-icon"><Icon name="search" size={16} /><input type="search" value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder={tab === 'customers' ? 'Customer name' : 'Invoice or customer'} /></div>
            </Field>
            {tab === 'invoices' && (
              <Field label="Bucket">
                <select value={bucket} onChange={(e) => { setBucket(e.target.value); setInvoicePage(1) }}>
                  <option value="">All buckets</option>
                  {BUCKET_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </Field>
            )}
          </div>

          {tab === 'customers' && (customers.error
            ? <ApiErrorBanner error={customers.error} title="Customers could not be loaded" onRetry={customers.reload} />
            : !customers.data ? <LoadingPanel label="Loading customers…" />
            : <>
              <DataTable<CustomerRow>
                ariaLabel="Customer receivables exposure"
                rows={customers.data.items}
                rowKey={(r) => r.customer_id}
                columns={[
                  { key: 'customer_name', label: 'Customer', render: (r) => <button type="button" className="link-button" onClick={() => onCustomer(r.customer_id)}>{r.customer_name}<Icon name="chevron" size={14} /></button> },
                  { key: 'total_outstanding', label: 'Outstanding', render: (r) => <CurrencyChips items={currencyAmountItems(r.currency_balances, 'total_outstanding')} /> },
                  { key: 'oldest_days_overdue', label: 'Oldest overdue', numeric: true, render: (r) => `${r.oldest_days_overdue}d` },
                  { key: 'credit_utilization', label: 'Credit utilization', numeric: true, render: (r) => (r.credit_utilization == null ? '—' : formatPercent(Number(r.credit_utilization) * 100, 0)) },
                  { key: 'priority_score', label: 'Score', numeric: true, render: (r) => <strong>{r.priority_score}</strong> },
                  { key: 'priority', label: 'Priority', render: (r) => <StatusBadge value={r.priority} toneMap={RISK_TONES} /> },
                ]}
              />
              <Pagination page={customers.data.page} pageSize={customers.data.page_size} total={customers.data.total} onPage={setCustomerPage} busy={customers.loading} />
            </>)}

          {tab === 'invoices' && (invoices.error
            ? <ApiErrorBanner error={invoices.error} title="Invoices could not be loaded" onRetry={invoices.reload} />
            : !invoices.data ? <LoadingPanel label="Loading invoices…" />
            : <>
              <DataTable<InvoiceRow>
                ariaLabel="Open receivable invoices"
                rows={invoices.data.items}
                rowKey={(r) => r.invoice_id}
                columns={[
                  { key: 'invoice_number', label: 'Invoice', render: (r) => <strong>{r.invoice_number}</strong> },
                  { key: 'customer_name', label: 'Customer' },
                  { key: 'invoice_date', label: 'Issued', render: (r) => formatDate(r.invoice_date) },
                  { key: 'due_date', label: 'Due', render: (r) => formatDate(r.due_date) },
                  { key: 'amount_outstanding', label: 'Outstanding', numeric: true, render: (r) => formatMoney(r.amount_outstanding, r.currency) },
                  { key: 'days_overdue', label: 'Days overdue', numeric: true, render: (r) => (r.days_overdue > 0 ? <span className="danger-number">{r.days_overdue}</span> : <span>{r.days_overdue}</span>) },
                  { key: 'bucket', label: 'Bucket', render: (r) => <StatusBadge value={r.bucket} toneMap={BUCKET_TONES} /> },
                ]}
              />
              <Pagination page={invoices.data.page} pageSize={invoices.data.page_size} total={invoices.data.total} onPage={setInvoicePage} busy={invoices.loading} />
            </>)}
        </Card>
      )}
    </div>
  )
}
