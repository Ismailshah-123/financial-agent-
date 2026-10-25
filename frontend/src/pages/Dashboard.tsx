import type { ReactElement, ReactNode } from 'react'
import { api } from '../api'
import { attentionItems, pipelineSegments } from '../chartData'
import { AgingBar, PipelineBar } from '../components/charts'
import { Icon } from '../components/Icons'
import Link from '../components/Link'
import {
  ApiErrorBanner, Card, CurrencyChips, DataTable, EmptyState, KpiCard, PageHeader, RISK_TONES, SectionHeading,
  Skeleton, SkeletonKpis, StatusBadge,
} from '../components/ui'
import { currencyAmountItems, formatDate, formatLabel, formatMoneyAmount, formatNumber } from '../formatters'
import { useAsync, type AsyncState } from '../hooks'
import { buildPath } from '../router'
import type { AgingSummary, ApSummary, ApprovalRequest, ApprovalSummary, Paginated, User } from '../types'

interface CustomerRow {
  customer_id: string
  customer_name: string
  currency_balances: { currency: string; total_outstanding: string }[]
  oldest_days_overdue: number
  priority_score: number
  priority: string
}

function greeting(user: User | null): string {
  const hour = new Date().getHours()
  const part = hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening'
  return `Good ${part}, ${user?.full_name?.split(' ')[0] || 'there'}.`
}

/** A KPI that reflects its own data source: loading and failure never read as zero. */
function kpi<T>(
  state: AsyncState<T | null>,
  render: (data: T) => { value: ReactNode; caption: ReactNode },
  props: { key: string; label: string; icon: string; tone: string },
): ReactElement {
  const { key, ...rest } = props
  if (state.data) return <KpiCard key={key} {...rest} {...render(state.data)} />
  return <KpiCard key={key} {...rest} value={state.loading ? '…' : 'Unavailable'} caption={state.loading ? 'Loading' : 'Could not be loaded. Use Retry in the panel below.'} />
}

export default function Dashboard({ can, user }: { can: (permission: string) => boolean; user: User | null }): ReactElement {
  const canAr = can('ar_invoice:read')
  const canAp = can('invoice:read')
  const canApprovals = can('approval_request:read')

  const aging = useAsync((signal) => (canAr ? api.get<AgingSummary>('/aging/summary', undefined, signal) : Promise.resolve(null)), [canAr])
  const ap = useAsync((signal) => (canAp ? api.get<ApSummary>('/ap-priority/summary', undefined, signal) : Promise.resolve(null)), [canAp])
  const summary = useAsync((signal) => (canApprovals ? api.get<ApprovalSummary>('/approval-requests/summary', undefined, signal) : Promise.resolve(null)), [canApprovals])
  const queue = useAsync((signal) => (canApprovals ? api.get<ApprovalRequest[]>('/approval-requests', { limit: 5 }, signal) : Promise.resolve(null)), [canApprovals])
  const customers = useAsync((signal) => (canAr ? api.get<Paginated<CustomerRow>>('/aging/customers', { page: 1, page_size: 5 }, signal) : Promise.resolve(null)), [canAr])

  const refreshAll = () => { aging.reload(); ap.reload(); summary.reload(); queue.reload(); customers.reload() }

  const kpis: ReactElement[] = []
  if (canAr) {
    kpis.push(kpi(aging, (a) => ({ value: <CurrencyChips items={currencyAmountItems(a.currency_balances, 'total_outstanding')} />, caption: `${a.open_invoice_count} open invoices` }), { key: 'ar', label: 'Total receivables', icon: 'users', tone: 'blue' }))
    kpis.push(kpi(aging, (a) => ({ value: <CurrencyChips items={currencyAmountItems(a.currency_balances, 'overdue_amount')} />, caption: `${a.overdue_invoice_count} invoices overdue` }), { key: 'overdue', label: 'Overdue receivables', icon: 'alert', tone: 'amber' }))
  }
  if (canAp) {
    kpis.push(kpi(ap, (a) => ({ value: <CurrencyChips items={currencyAmountItems(a.currency_balances, 'total_payable')} />, caption: `${a.open_obligation_count} open obligations` }), { key: 'ap', label: 'Total payables', icon: 'wallet', tone: 'violet' }))
    kpis.push(kpi(ap, (a) => ({ value: <CurrencyChips items={currencyAmountItems(a.currency_balances, 'overdue_amount')} />, caption: `${a.overdue_count} obligations overdue` }), { key: 'apoverdue', label: 'Payables overdue', icon: 'calendar', tone: 'rose' }))
  }
  if (canApprovals) {
    kpis.push(kpi(summary, (s) => ({ value: formatNumber(s.pending), caption: `${formatNumber(s.awaiting_execution)} approved and awaiting execution${s.failed ? `, ${s.failed} failed` : ''}` }), { key: 'approvals', label: 'Pending approvals', icon: 'inbox', tone: 'green' }))
  }

  // Everything that needs a person, taken only from counts the API returned.
  const attention = attentionItems({
    failedExecutions: summary.data?.failed,
    pendingApprovals: summary.data?.pending,
    awaitingExecution: summary.data?.awaiting_execution,
    overdueReceivables: aging.data?.overdue_invoice_count,
    overduePayables: ap.data?.overdue_count,
  })
  const sourcesSettled = [canAr ? aging : null, canAp ? ap : null, canApprovals ? summary : null].every((state) => state === null || (!state.loading && state.data !== null))
  const anySource = canAr || canAp || canApprovals
  const anyError = [aging, ap, summary].some((state) => state.error !== null)

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Executive view"
        title={greeting(user)}
        description="Current finance exposure and the work waiting for attention. Amounts are shown per currency; no currency conversion is applied."
        action={<button type="button" className="icon-button" onClick={refreshAll} aria-label="Refresh overview" title="Refresh overview"><Icon name="refresh" size={17} /></button>}
      />

      {anySource && (
        <section className={`attention-strip ${attention.length || anyError ? 'has-items' : 'clear'}`} aria-label="What needs attention">
          <div className="attention-lead">
            <span className="attention-badge" aria-hidden="true"><Icon name={attention.length ? 'alert' : 'check'} size={18} /></span>
            <div>
              <strong>{attention.length ? `${attention.length} thing${attention.length === 1 ? '' : 's'} need${attention.length === 1 ? 's' : ''} attention` : anyError ? 'Some figures could not be loaded' : sourcesSettled ? 'Nothing needs attention right now' : 'Checking what needs attention…'}</strong>
              <span>{attention.length ? 'Most urgent first. Each opens the workspace where you can act.' : anyError ? 'The panels below show which source failed. This summary is incomplete until they load.' : sourcesSettled ? 'No failed executions, pending decisions or overdue items were reported.' : 'Waiting for the finance API.'}</span>
            </div>
          </div>
          {attention.length > 0 && (
            <ul className="attention-list">
              {attention.map((item) => (
                <li key={item.key} className={`tone-${item.tone}`}>
                  <span>{item.text}</span>
                  <Link to={buildPath(item.to)} className="text-button">Open <Icon name="arrow" size={13} /></Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {kpis.length > 0 ? <div className="kpi-grid">{kpis}</div> : anySource ? <SkeletonKpis /> : (
        <EmptyState title="No finance data is available to your role" description="Ask an administrator to grant receivables, payables or approval access." />
      )}

      <div className="dashboard-grid">
        <Card>
          <SectionHeading title="Receivables aging" description="Open AR by how late it is, one bar per currency." action={aging.data ? <span className="muted-label">As of {formatDate(aging.data.as_of)}</span> : undefined} />
          {!canAr ? <EmptyState title="Receivables unavailable" description="Your current role does not have AR read access." />
            : aging.error ? <ApiErrorBanner error={aging.error} title="Receivables could not be loaded" onRetry={aging.reload} />
            : !aging.data ? <Skeleton lines={4} label="Loading receivables" />
            : aging.data.currency_balances.length === 0 ? <EmptyState title="No open receivables" description="There is no open exposure with a reportable currency." />
            : <div className="chart-stack">{aging.data.currency_balances.map((balance) => (
              <AgingBar key={balance.currency} balance={balance as unknown as Record<string, unknown>} currency={balance.currency} />
            ))}</div>}
        </Card>

        <Card>
          <SectionHeading title="Approval pipeline" description="Where recommendations are in their lifecycle." action={summary.data ? <span className="count-pill" aria-label={`${summary.data.pending} pending`}>{summary.data.pending}</span> : undefined} />
          {!canApprovals ? <EmptyState title="Approval access unavailable" description="Your current role does not have permission to view the approval queue." />
            : summary.error ? <ApiErrorBanner error={summary.error} title="Approvals could not be loaded" onRetry={summary.reload} />
            : !summary.data ? <Skeleton lines={3} label="Loading approvals" />
            : <>
              <PipelineBar label="Approval pipeline" segments={pipelineSegments(summary.data)} />
              {queue.data && queue.data.length > 0 && (
                <div className="compact-list">
                  {queue.data.map((item) => (
                    <div className="list-row" key={item.id}>
                      <div><strong>{formatLabel(item.agent_type)}</strong><span>{item.summary}</span></div>
                      <StatusBadge value={item.risk_level} toneMap={RISK_TONES} />
                    </div>
                  ))}
                </div>
              )}
              {queue.data && queue.data.length === 0 && <p className="muted-label">No recommendations are waiting for a decision.</p>}
              <Link to={buildPath('approvals')} className="text-button">Open approval inbox <Icon name="arrow" size={14} /></Link>
            </>}
        </Card>
      </div>

      <div className="dashboard-grid">
        <Card>
          <SectionHeading title="Payables exposure" description="Current payment obligations by status and currency." />
          {!canAp ? <EmptyState title="Payables unavailable" description="Your current role does not have AP read access." />
            : ap.error ? <ApiErrorBanner error={ap.error} title="Payables could not be loaded" onRetry={ap.reload} />
            : !ap.data ? <Skeleton lines={4} label="Loading payables" />
            : ap.data.currency_balances.length === 0 ? <EmptyState title="No open payables" description="No payment obligations with a reportable currency were returned." />
            : <div className="exposure-list">{ap.data.currency_balances.flatMap((balance) => Object.entries(balance.by_status_amount ?? {}).map(([status, amount]) => (
              <div className="exposure-line" key={`${balance.currency}-${status}`}>
                <span>{formatLabel(status)} · {balance.currency}</span>
                <strong>{formatMoneyAmount(amount, balance.currency)}</strong>
                <em aria-label={`${balance.by_status_count?.[status] ?? 0} obligations`}>{balance.by_status_count?.[status] ?? 0}</em>
              </div>
            )))}</div>}
        </Card>
        <Card className="attention-card">
          <div className="attention-mark" aria-hidden="true"><Icon name="plug" size={20} /></div>
          <div>
            <div className="eyebrow">SAP Business One</div>
            <h3>Integration workspace</h3>
            <p>Check the Service Layer connection and run master data synchronization. A configured URL is not proof of a live connection; the workspace shows the verified state.</p>
            {can('agent:invoke') && <Link to={buildPath('sap')} className="text-button">Open SAP integration <Icon name="arrow" size={14} /></Link>}
          </div>
        </Card>
      </div>

      <Card>
        <SectionHeading title="Collection priorities" description="Customers ordered by the backend collection priority model." />
        {!canAr ? <EmptyState title="No AR access" description="Collection priorities are hidden for this role." />
          : customers.error ? <ApiErrorBanner error={customers.error} title="Collection priorities could not be loaded" onRetry={customers.reload} />
          : !customers.data ? <Skeleton lines={4} label="Loading collection priorities" />
          : <DataTable<CustomerRow>
            ariaLabel="Top collection priorities"
            rows={customers.data.items}
            rowKey={(r) => r.customer_id}
            columns={[
              { key: 'customer_name', label: 'Customer', render: (r) => <Link to={buildPath('customer', { id: r.customer_id })} className="link-button">{r.customer_name}</Link> },
              { key: 'total_outstanding', label: 'Outstanding', render: (r) => <CurrencyChips items={currencyAmountItems(r.currency_balances, 'total_outstanding')} /> },
              { key: 'oldest_days_overdue', label: 'Oldest overdue', numeric: true, render: (r) => `${r.oldest_days_overdue} days` },
              { key: 'priority_score', label: 'Score', numeric: true, render: (r) => <strong>{r.priority_score}</strong> },
              { key: 'priority', label: 'Priority', render: (r) => <StatusBadge value={r.priority} toneMap={RISK_TONES} /> },
            ]}
          />}
      </Card>
    </div>
  )
}
