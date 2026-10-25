import { useEffect, useState, type ReactElement } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icons'
import {
  ApiErrorBanner, Button, Card, DataTable, EmptyState, Field, LoadingPanel, Notice, PageHeader, SectionHeading, StatusBadge, Tabs,
  type Column,
} from '../components/ui'
import { downloadTextFile, toCsv } from '../csv'
import { formatDate, formatMoneyAmount, localDateInputValue } from '../formatters'
import { useAsync } from '../hooks'
import type { AccountBalanceLine, BalanceSheetReport, ProfitAndLossReport, ReportCurrencies, TrialBalanceReport } from '../types'

type Tab = 'trial' | 'pnl' | 'balance'
type Report = TrialBalanceReport | ProfitAndLossReport | BalanceSheetReport

function lineColumns(currency: string): Column<AccountBalanceLine>[] {
  const money = (value: string) => formatMoneyAmount(value, currency)
  return [
    { key: 'account_code', label: 'Code' },
    { key: 'account_name', label: 'Account', render: (r) => <strong>{r.account_name}</strong> },
    { key: 'account_type', label: 'Type' },
    { key: 'total_debit', label: `Debit (${currency})`, numeric: true, render: (r) => money(r.total_debit) },
    { key: 'total_credit', label: `Credit (${currency})`, numeric: true, render: (r) => money(r.total_credit) },
    { key: 'balance', label: `Balance (${currency})`, numeric: true, render: (r) => money(r.balance) },
  ]
}

function Stat({ label, value, currency, flag }: { label: string; value: string; currency: string; flag?: boolean }): ReactElement {
  return (
    <div className="mini-kpi">
      <span>{label}</span>
      <strong>{formatMoneyAmount(value, currency)} <small className="unit">{currency}</small></strong>
      {flag && <StatusBadge value="attention" toneMap={{ attention: 'rose' }} />}
    </div>
  )
}

function Balanced({ ok }: { ok: boolean }): ReactElement {
  return (
    <div className="mini-kpi">
      <span>Balanced</span>
      <strong>{ok ? 'Yes' : 'No'}</strong>
      {!ok && <StatusBadge value="attention" toneMap={{ attention: 'rose' }} />}
    </div>
  )
}

function reportCsv(tab: Tab, report: Report): string {
  const header = ['Section', 'Code', 'Account', 'Type', 'Debit', 'Credit', 'Balance', 'Currency']
  const rows: unknown[][] = [header]
  const add = (section: string, lines: AccountBalanceLine[]) => lines.forEach((l) => rows.push([section, l.account_code, l.account_name, l.account_type, l.total_debit, l.total_credit, l.balance, report.currency]))
  if (tab === 'trial') add('Trial balance', (report as TrialBalanceReport).lines)
  if (tab === 'pnl') { const r = report as ProfitAndLossReport; add('Revenue', r.revenue_lines); add('Expenses', r.expense_lines) }
  if (tab === 'balance') { const r = report as BalanceSheetReport; add('Assets', r.asset_lines); add('Liabilities', r.liability_lines); add('Equity', r.equity_lines) }
  return toCsv(rows)
}

export default function Reports(): ReactElement {
  const today = localDateInputValue()
  const [tab, setTab] = useState<Tab>('trial')
  const [asOf, setAsOf] = useState(today)
  const [start, setStart] = useState(`${today.slice(0, 7)}-01`)
  const [end, setEnd] = useState(today)
  const [currency, setCurrency] = useState('')
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const currencies = useAsync((signal) => api.get<ReportCurrencies>('/reports/currencies', undefined, signal), [])
  const available = currencies.data?.currencies ?? []

  // A single posted currency is selected for the user; several force an explicit choice.
  useEffect(() => {
    if (available.length === 1) setCurrency(available[0])
    else if (currency && !available.includes(currency)) setCurrency('')
  }, [available.join(',')])

  useEffect(() => { setReport(null); setError(null) }, [tab, currency])

  const rangeInvalid = tab === 'pnl' && start > end
  const canRun = Boolean(currency) && !rangeInvalid && !loading

  async function run(): Promise<void> {
    if (!canRun) return
    setLoading(true)
    setError(null)
    setReport(null)
    try {
      if (tab === 'trial') setReport(await api.get<TrialBalanceReport>('/reports/trial-balance', { as_of: asOf, currency }))
      else if (tab === 'pnl') setReport(await api.get<ProfitAndLossReport>('/reports/profit-and-loss', { start_date: start, end_date: end, currency }))
      else setReport(await api.get<BalanceSheetReport>('/reports/balance-sheet', { as_of: asOf, currency }))
    } catch (caught) {
      setError(caught)
    } finally {
      setLoading(false)
    }
  }

  const unit = report?.currency ?? currency

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Financial reporting"
        title="Reports"
        description="Trial balance, profit and loss, and balance sheet from the General Ledger. Each report covers one currency; amounts in different currencies are never combined and no exchange rate is applied."
        action={<button type="button" className="icon-button" onClick={currencies.reload} aria-label="Reload currencies" title="Reload currencies"><Icon name="refresh" size={17} /></button>}
      />
      <Tabs
        label="Report type"
        items={[{ key: 'trial', label: 'Trial balance' }, { key: 'pnl', label: 'Profit & Loss' }, { key: 'balance', label: 'Balance sheet' }]}
        value={tab}
        onChange={(key) => setTab(key as Tab)}
      />
      <Card>
        {currencies.error && <ApiErrorBanner error={currencies.error} title="Ledger currencies could not be loaded" onRetry={currencies.reload} />}
        {currencies.data && available.length === 0 && (
          <EmptyState title="No posted journal entries" description="Reports become available once at least one journal entry has been posted to the ledger." />
        )}
        {available.length > 0 && (
          <form className="report-controls" onSubmit={(event) => { event.preventDefault(); void run() }}>
            {tab === 'pnl' ? <>
              <Field label="Start date"><input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} required /></Field>
              <Field label="End date"><input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} required /></Field>
            </> : <Field label="As of"><input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} required /></Field>}
            <Field label="Currency" hint={available.length > 1 ? 'The ledger holds several currencies. Choose one.' : undefined}>
              <select value={currency} onChange={(e) => setCurrency(e.target.value)} required>
                {available.length > 1 && <option value="">Choose a currency</option>}
                {available.map((code) => <option key={code} value={code}>{code}</option>)}
              </select>
            </Field>
            <Button type="submit" disabled={!canRun}>{loading ? 'Running…' : 'Run report'}</Button>
          </form>
        )}
        {rangeInvalid && <div className="inline-error" role="alert"><Icon name="alert" size={16} />The start date must be on or before the end date.</div>}
        {error !== null && <ApiErrorBanner error={error} title="The report could not be produced" />}
        {loading && <LoadingPanel label="Running accounting report…" />}
        {!loading && !report && !error && available.length > 0 && (
          <EmptyState title="Choose your reporting date" description={currency ? 'Run the selected report against the General Ledger.' : 'Choose a currency, then run the report.'} />
        )}

        {report && !loading && (
          <div aria-live="polite">
            <Notice tone="info" icon="file" live="none">All amounts are in <strong>{unit}</strong>. {report.available_currencies.length > 1 ? `The ledger also holds ${report.available_currencies.filter((c) => c !== unit).join(', ')}; those are reported separately.` : ''}</Notice>
            <div className="report-actions">
              <Button variant="secondary" icon="file" onClick={() => downloadTextFile(`${tab}-${unit}-${tab === 'pnl' ? `${start}_${end}` : asOf}.csv`, reportCsv(tab, report))}>Download CSV</Button>
            </div>
            {tab === 'trial' && <>
              <div className="kpi-grid three">
                <Stat label="Total debit" value={(report as TrialBalanceReport).total_debit} currency={unit} />
                <Stat label="Total credit" value={(report as TrialBalanceReport).total_credit} currency={unit} />
                <Balanced ok={(report as TrialBalanceReport).is_balanced} />
              </div>
              <DataTable<AccountBalanceLine> ariaLabel={`Trial balance in ${unit}`} rows={(report as TrialBalanceReport).lines} rowKey={(r) => r.account_code} columns={lineColumns(unit)} emptyTitle="No postings" emptyDescription={`No ${unit} journal entries are posted on or before this date.`} />
            </>}
            {tab === 'pnl' && (() => {
              const r = report as ProfitAndLossReport
              return <>
                <div className="kpi-grid three">
                  <Stat label="Revenue" value={r.total_revenue} currency={unit} />
                  <Stat label="Expense" value={r.total_expense} currency={unit} />
                  <Stat label="Net income" value={r.net_income} currency={unit} />
                </div>
                <div className="report-section"><SectionHeading title="Revenue" description={`${formatDate(r.start_date)} to ${formatDate(r.end_date)}`} /><DataTable<AccountBalanceLine> ariaLabel={`Revenue lines in ${unit}`} rows={r.revenue_lines} rowKey={(l) => l.account_code} columns={lineColumns(unit)} emptyTitle="No revenue" emptyDescription="No revenue was posted in this period." /></div>
                <div className="report-section"><SectionHeading title="Expenses" /><DataTable<AccountBalanceLine> ariaLabel={`Expense lines in ${unit}`} rows={r.expense_lines} rowKey={(l) => l.account_code} columns={lineColumns(unit)} emptyTitle="No expenses" emptyDescription="No expenses were posted in this period." /></div>
              </>
            })()}
            {tab === 'balance' && (() => {
              const r = report as BalanceSheetReport
              return <>
                <div className="kpi-grid">
                  <Stat label="Total assets" value={r.total_assets} currency={unit} />
                  <Stat label="Liabilities" value={r.total_liabilities} currency={unit} />
                  <Stat label="Equity" value={r.total_equity} currency={unit} />
                  <Balanced ok={r.is_balanced} />
                </div>
                <Notice tone="info" icon="file" live="none">As of {formatDate(r.as_of)}. Retained earnings ({formatMoneyAmount(r.computed_retained_earnings, unit)} {unit}) is computed from posted revenue and expense, not from a closed period. Treat this as management reporting, not an audited close.</Notice>
                {([['Assets', r.asset_lines], ['Liabilities', r.liability_lines], ['Equity', r.equity_lines]] as [string, AccountBalanceLine[]][]).map(([title, lines]) => (
                  <div className="report-section" key={title}><SectionHeading title={title} /><DataTable<AccountBalanceLine> ariaLabel={`${title} in ${unit}`} rows={lines} rowKey={(l) => l.account_code} columns={lineColumns(unit)} emptyTitle={`No ${title.toLowerCase()}`} emptyDescription="Nothing is posted to these accounts." /></div>
                ))}
              </>
            })()}
          </div>
        )}
      </Card>
    </div>
  )
}
