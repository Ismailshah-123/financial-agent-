import { useState, type ReactElement } from 'react'
import { api } from '../api'
import { AgingBar } from '../components/charts'
import { Icon } from '../components/Icons'
import {
  ApiErrorBanner, Button, Card, CurrencyChips, EmptyState, KpiCard, PageHeader, RISK_TONES, SectionHeading, Skeleton,
  SkeletonKpis, StatusBadge,
} from '../components/ui'
import { currencyAmountItems, formatDate, formatMoney, formatPercent } from '../formatters'
import { useAsync } from '../hooks'
import type { AgentRunResult, CustomerAging } from '../types'

interface CustomerDetailProps {
  id: string
  onBack: () => void
  can: (permission: string) => boolean
}

export default function CustomerDetail({ id, onBack, can }: CustomerDetailProps): ReactElement {
  const customer = useAsync((signal) => api.get<CustomerAging>(`/aging/customer/${id}`, undefined, signal), [id])
  const [agentResult, setAgentResult] = useState<AgentRunResult | null>(null)
  const [agentError, setAgentError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function run(): Promise<void> {
    if (busy) return
    setBusy(true)
    setAgentError(null)
    try {
      setAgentResult(await api.post<AgentRunResult>('/agents/collections/run', { customer_id: id }))
    } catch (error) {
      setAgentError(error)
    } finally {
      setBusy(false)
    }
  }

  const back = (
    <button type="button" className="back-link" onClick={onBack}><Icon name="chevron" size={14} /> Back to receivables</button>
  )

  if (customer.error && !customer.data) {
    return (
      <div className="page-stack">
        {back}
        <ApiErrorBanner error={customer.error} title="Customer could not be loaded" onRetry={customer.reload} />
      </div>
    )
  }
  if (!customer.data) {
    return <div className="page-stack">{back}<SkeletonKpis count={4} /><Skeleton lines={4} label="Loading customer exposure" /></div>
  }

  const data = customer.data
  const balances = data.currency_balances ?? []
  const multi = balances.length > 1
  const creditUtilization = multi
    ? 'See per currency exposure'
    : data.credit_utilization == null
      ? 'Not configured'
      : formatPercent(Number(data.credit_utilization) * 100, 0)

  return (
    <div className="page-stack">
      {back}
      <PageHeader
        eyebrow="Customer intelligence"
        title={data.customer_name}
        description="Customer level AR exposure, backend priority signals, and an explicit AI assessment."
        action={can('agent:invoke') ? <Button variant="secondary" icon="bot" disabled={busy} onClick={() => void run()}>{busy ? 'Assessing…' : 'Run collection assessment'}</Button> : null}
      />
      {agentError !== null && <ApiErrorBanner error={agentError} title="Assessment needs attention" />}
      <div className="kpi-grid">
        <KpiCard label="Outstanding" value={<CurrencyChips items={currencyAmountItems(balances, 'total_outstanding')} />} caption={`${data.open_invoice_count} open invoices`} icon="wallet" tone="blue" />
        <KpiCard label="Overdue" value={<CurrencyChips items={currencyAmountItems(balances, 'overdue_amount')} />} caption={`${data.overdue_invoice_count} overdue`} icon="alert" tone="amber" />
        <KpiCard label="Priority score" value={data.priority_score} caption={`Risk: ${data.risk}`} icon="chart" tone="violet" />
        <KpiCard label="Oldest overdue" value={`${data.oldest_days_overdue}d`} caption={`Due ${formatDate(data.oldest_due_date)}`} icon="calendar" tone="rose" />
      </div>

      <div className="dashboard-grid">
        <Card>
          <SectionHeading title="Rule based assessment" description="Backend derived facts; not recalculated by the frontend." />
          <div className="fact-list">
            <div><span>Priority</span><strong><StatusBadge value={data.priority} toneMap={RISK_TONES} /></strong></div>
            <div><span>Credit utilization</span><strong>{creditUtilization}</strong></div>
            <div><span>Recommended action</span><strong>{data.recommended_action}</strong></div>
          </div>
          <div className="reason-list">{(data.priority_reasons ?? []).map((reason) => <div key={reason}><Icon name="check" size={14} />{reason}</div>)}</div>
        </Card>
        <Card>
          <SectionHeading title="AI generated explanation" description="Populated only when the Collections Agent is explicitly run." />
          {agentResult
            ? (agentResult.decisions ?? []).map((decision, index) => (
              <div className="ai-explanation" key={decision.decision_id ?? `${decision.summary}-${index}`}>
                <div className="decision-title"><StatusBadge value={decision.risk_level} toneMap={RISK_TONES} /><h3>{decision.summary}</h3></div>
                <p>{decision.reasoning}</p>
                <small>Confidence: {decision.confidence ? formatPercent(Number(decision.confidence.value) * 100, 0) : 'not provided'}</small>
              </div>
            ))
            : <EmptyState title="No AI explanation yet" description="Run the Collections Agent to generate an explanation alongside deterministic customer facts." />}
        </Card>
      </div>

      <Card>
        <SectionHeading title="Exposure by currency" description="Each balance comes from the backend. No foreign exchange conversion is configured, so currencies are never added together." />
        {balances.length
          ? <div className="chart-stack">{balances.map((balance) => (
            <div key={balance.currency}>
              <AgingBar balance={balance as unknown as Record<string, unknown>} currency={balance.currency} />
              <p className="chart-foot">{balance.open_invoice_count} open invoice(s), {formatMoney(balance.overdue_amount, balance.currency)} overdue</p>
            </div>
          ))}</div>
          : <EmptyState title="No open currency balances" description="No positive outstanding invoices were found for this customer." />}
      </Card>
    </div>
  )
}
