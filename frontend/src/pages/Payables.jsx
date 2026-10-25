import { useEffect, useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icons'
import { Card, DataTable, EmptyState, Field, KpiCard, LoadingPanel, PageHeader, SectionHeading, StatusBadge, Tabs } from '../components/ui'
import { formatCurrencyAmounts, formatDate as fmt, formatLabel as label, formatMoney as money, formatNumber } from '../formatters'

const PAGE_SIZE = 25

export default function Payables({ onVendor }) {
  const [tab, setTab] = useState('summary')
  const [summary, setSummary] = useState(null)
  const [obligations, setObligations] = useState(null)
  const [vendors, setVendors] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [listLoading, setListLoading] = useState(false)
  const [summaryError, setSummaryError] = useState('')
  const [listError, setListError] = useState('')
  const [refreshCount, setRefreshCount] = useState(0)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [page, setPage] = useState(1)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim())
      setPage(1)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  async function loadSummary() {
    setSummaryLoading(true)
    setSummaryError('')
    try {
      setSummary(await api.get('/ap-priority/summary'))
    } catch (err) {
      setSummaryError(err?.message || 'Payables summary could not be loaded.')
    } finally {
      setSummaryLoading(false)
    }
  }

  useEffect(() => { void loadSummary() }, [refreshCount])

  useEffect(() => {
    if (tab !== 'obligations' && tab !== 'vendors') return
    let active = true
    setListLoading(true)
    setListError('')
    const request = tab === 'obligations'
      ? api.get('/ap-priority/obligations', {
          page,
          page_size: PAGE_SIZE,
          search: search || undefined,
          status: status || undefined,
          priority: priority || undefined,
        })
      : api.get('/ap-priority/vendors', { page, page_size: PAGE_SIZE, search: search || undefined })

    request
      .then((result) => {
        if (!active) return
        if (tab === 'obligations') setObligations(result)
        else setVendors(result)
      })
      .catch((err) => {
        if (active) setListError(err?.message || 'Payables records could not be loaded.')
      })
      .finally(() => { if (active) setListLoading(false) })

    return () => { active = false }
  }, [tab, page, search, status, priority, refreshCount])

  function changeTab(nextTab) {
    setTab(nextTab)
    setPage(1)
    setSearchInput('')
    setSearch('')
    setStatus('')
    setPriority('')
    setListError('')
    setSummaryError('')
  }

  const tabs = [
    { key: 'summary', label: 'Summary' },
    { key: 'obligations', label: 'Obligations' },
    { key: 'vendors', label: 'Vendor exposure' },
  ]

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Accounts payable"
        title="Payables"
        description="Payment obligations, vendor exposure, and urgency signals from the backend AP priority service."
        action={<button className="icon-button" onClick={() => setRefreshCount((count) => count + 1)} title="Refresh payables"><Icon name="refresh" size={17} /></button>}
      />
      {(tab === 'summary' ? summaryError : listError) && <div className="error-banner" role="alert"><div><strong>Payables data needs attention</strong><span>{tab === 'summary' ? summaryError : listError}</span></div><button className="button button-secondary" onClick={() => setRefreshCount((count) => count + 1)}><Icon name="refresh" size={15} /> Retry</button></div>}

      {summaryLoading && !summary ? <LoadingPanel label="Loading payables summary…" /> : summary && <div className="kpi-grid">
        <KpiCard label="Total payable" value={formatCurrencyAmounts(summary.currency_balances,'total_payable',summary.total_payable,summary.currency)} caption={`${formatNumber(summary.open_obligation_count)} open obligations`} icon="wallet" tone="blue" />
        <KpiCard label="Overdue amount" value={formatCurrencyAmounts(summary.currency_balances,'overdue_amount',summary.overdue_amount,summary.currency)} caption={`${formatNumber(summary.overdue_count)} overdue obligations`} icon="alert" tone="amber" />
        <KpiCard label="Executed — 30d" value={formatCurrencyAmounts(summary.currency_balances,'executed_last_30_days_amount',summary.executed_last_30_days_amount,summary.currency)} caption={`${formatNumber(summary.executed_last_30_days_count)} payments`} icon="check" tone="green" />
      </div>}

      <Tabs items={tabs} value={tab} onChange={changeTab} />
      {tab === 'summary' && (summary ? <Summary summary={summary} /> : !summaryLoading && !summaryError && <EmptyState title="Payables summary unavailable" description="The backend did not return a summary. Retry when the API is healthy." />)}
      {(tab === 'obligations' || tab === 'vendors') && <>
        <Card>
          <div className="filter-bar payables-filters">
            <Field label={tab === 'vendors' ? 'Search vendor' : 'Search invoice or vendor'}>
              <div className="input-with-icon"><Icon name="search" size={16} /><input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder={tab === 'vendors' ? 'Vendor name' : 'Invoice number or vendor'} /></div>
            </Field>
            {tab === 'obligations' && <>
              <Field label="Status"><select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }}><option value="">All statuses</option>{['blocked', 'payment_failed', 'awaiting_approval', 'ready_to_schedule', 'scheduled', 'executed'].map((value) => <option value={value} key={value}>{label(value)}</option>)}</select></Field>
              <Field label="Priority"><select value={priority} onChange={(event) => { setPriority(event.target.value); setPage(1) }}><option value="">All priorities</option>{['low', 'medium', 'high', 'critical'].map((value) => <option value={value} key={value}>{label(value)}</option>)}</select></Field>
            </>}
          </div>
        </Card>
        {listLoading ? <LoadingPanel label={tab === 'obligations' ? 'Loading payment obligations…' : 'Loading vendor exposure…'} /> : tab === 'obligations' ? <Obligations result={obligations} /> : <Vendors result={vendors} onVendor={onVendor} />}
        {!listLoading && <Pagination result={tab === 'obligations' ? obligations : vendors} page={page} setPage={setPage} />}
      </>}
    </div>
  )
}

function Summary({ summary }) {
  return <div className="dashboard-grid">
    <Card>
      <SectionHeading title="Open obligation status" description="Amounts and status categories are computed by the backend." />
      <div className="exposure-list">{(summary.currency_balances||[]).length?summary.currency_balances.flatMap((balance)=>Object.entries(balance.by_status_amount||{}).map(([key,amount])=><div className="exposure-line" key={`${balance.currency}-${key}`}><span>{label(key)} · {balance.currency}</span><strong>{money(amount,balance.currency)}</strong><em>{formatNumber(balance.by_status_count?.[key])}</em></div>)):<p className="muted-label">No payable exposure available.</p>}</div>
    </Card>
    <Card>
      <SectionHeading title="Payment health" />
      <div className="signal-grid"><div><span>Open obligations</span><strong>{formatNumber(summary.open_obligation_count)}</strong></div><div><span>Overdue count</span><strong>{formatNumber(summary.overdue_count)}</strong></div><div><span>Last 30d payments</span><strong>{formatNumber(summary.executed_last_30_days_count)}</strong></div><div><span>Last 30d value</span><strong>{formatCurrencyAmounts(summary.currency_balances, 'executed_last_30_days_amount', summary.executed_last_30_days_amount, summary.currency)}</strong></div></div>
      <div className="callout warning"><Icon name="alert" size={17} /><span>Payment prioritization is read-only in this release. Failed obligations are surfaced, but retry/reschedule is intentionally not implemented.</span></div>
    </Card>
  </div>
}

function Obligations({ result }) {
  if (!result) return <Card><EmptyState title="No obligation result" description="Run the query again to load payment obligations." /></Card>
  return <Card>
    <SectionHeading title="Payment obligations" description={`${formatNumber(result.total)} matching records · page ${result.page} of ${Math.max(1, Math.ceil(result.total / result.page_size))}.`} />
    <DataTable rows={result.items} rowKey={(row) => row.invoice_id} ariaLabel="Payment obligations" columns={[
      { key: 'vendor_name', label: 'Vendor', render: (row) => <strong>{row.vendor_name}</strong> },
      { key: 'invoice_number', label: 'Invoice' },
      { key: 'amount', label: 'Amount', render: (row) => money(row.amount, row.currency) },
      { key: 'due_date', label: 'Due', render: (row) => fmt(row.due_date) },
      { key: 'timing', label: 'Timing', render: (row) => row.days_until_due < 0 ? <span className="danger-number">{Math.abs(row.days_until_due)}d overdue</span> : row.days_until_due === 0 ? 'Due today' : `${row.days_until_due}d` },
      { key: 'status', label: 'Status', render: (row) => <StatusBadge value={row.status} toneMap={{ blocked: 'rose', payment_failed: 'rose', awaiting_approval: 'amber', ready_to_schedule: 'blue', scheduled: 'violet', executed: 'green' }} /> },
      { key: 'priority', label: 'Priority', render: (row) => row.priority ? <StatusBadge value={row.priority} toneMap={{ low: 'green', medium: 'blue', high: 'amber', critical: 'rose' }} /> : '—' },
    ]} />
  </Card>
}

function Vendors({ result, onVendor }) {
  if (!result) return <Card><EmptyState title="No vendor result" description="Run the query again to load vendor exposure." /></Card>
  return <Card>
    <SectionHeading title="Vendor exposure" description={`${formatNumber(result.total)} vendors match the current search.`} />
    <DataTable rows={result.items} rowKey={(row) => row.vendor_id} ariaLabel="Vendor exposure" columns={[
      { key: 'vendor_name', label: 'Vendor', render: (row) => onVendor ? <button className="link-button" onClick={() => onVendor(row.vendor_id)}>{row.vendor_name}<Icon name="chevron" size={14} /></button> : <strong>{row.vendor_name}</strong> },
      { key: 'total_exposure', label: 'Exposure', render: (row) => formatCurrencyAmounts(row.currency_balances, 'total_exposure', row.total_exposure, row.currency) },
      { key: 'overdue_amount', label: 'Overdue', render: (row) => formatCurrencyAmounts(row.currency_balances, 'overdue_amount', row.overdue_amount, row.currency) },
      { key: 'open_invoice_count', label: 'Open invoices', render: (row) => formatNumber(row.open_invoice_count) },
      { key: 'payment_failed_count', label: 'Failed payments', render: (row) => row.payment_failed_count > 0 ? <span className="danger-number">{formatNumber(row.payment_failed_count)}</span> : '0' },
      { key: 'highest_priority', label: 'Highest priority', render: (row) => <StatusBadge value={row.highest_priority} toneMap={{ low: 'green', medium: 'blue', high: 'amber', critical: 'rose' }} /> },
    ]} />
  </Card>
}

function Pagination({ result, page, setPage }) {
  const totalPages = Math.max(1, Math.ceil((result?.total || 0) / (result?.page_size || PAGE_SIZE)))
  return <div className="pagination"><span>Page {page} of {totalPages}</span><div><button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><button disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</button></div></div>
}
