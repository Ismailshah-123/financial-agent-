import { useEffect, useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icons'
import {
  Button,
  Card,
  EmptyState,
  KpiCard,
  LoadingPanel,
  PageHeader,
  SectionHeading,
  StatusBadge,
} from '../components/ui'
import { formatCurrencyAmounts, formatDate as fmt, formatMoney, formatPercent } from '../formatters'

export default function CustomerDetail({ id, onBack, can }) {
  const [customer, setCustomer] = useState(null)
  const [agentResult, setAgentResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    setCustomer(null)
    setAgentResult(null)
    setError('')
    api.get(`/aging/customer/${id}`)
      .then((result) => { if (active) setCustomer(result) })
      .catch((err) => { if (active) setError(err.message || 'Customer exposure could not be loaded.') })
    return () => { active = false }
  }, [id])

  async function run() {
    setBusy(true)
    setError('')
    try {
      setAgentResult(await api.post('/agents/collections/run', { customer_id: id }))
    } catch (err) {
      setError(err.message || 'Collection assessment failed.')
    } finally {
      setBusy(false)
    }
  }

  if (!customer && !error) return <LoadingPanel label="Loading customer exposure…" />
  if (error && !customer) {
    return <div className="page-stack">
      <button className="back-link" onClick={onBack}><Icon name="chevron" size={14} /> Back to receivables</button>
      <div className="error-banner"><div><strong>Customer could not be loaded</strong><span>{error}</span></div></div>
    </div>
  }

  const balances = customer.currency_balances || []
  const amount = (key) => formatCurrencyAmounts(balances, key, customer[key], customer.currency)
  const creditUtilization = balances.length > 1
    ? 'See per-currency exposure'
    : customer.credit_utilization == null
      ? 'Not configured'
      : formatPercent(Number(customer.credit_utilization) * 100, 0)

  return <div className="page-stack">
    <button className="back-link" onClick={onBack}><Icon name="chevron" size={14} /> Back to receivables</button>
    <PageHeader
      eyebrow="Customer intelligence"
      title={customer.customer_name}
      description="Customer-level AR exposure, backend priority signals, and an explicit AI assessment."
      action={can('agent:invoke') ? <Button variant="secondary" icon="bot" disabled={busy} onClick={run}>{busy ? 'Assessing…' : 'Run collection assessment'}</Button> : null}
    />
    {error && <div className="error-banner"><div><strong>Assessment needs attention</strong><span>{error}</span></div></div>}
    <div className="kpi-grid">
      <KpiCard label="Outstanding" value={amount('total_outstanding')} caption={`${customer.open_invoice_count} open invoices`} icon="wallet" tone="blue" />
      <KpiCard label="Overdue" value={amount('overdue_amount')} caption={`${customer.overdue_invoice_count} overdue`} icon="alert" tone="amber" />
      <KpiCard label="Priority score" value={customer.priority_score} caption={`Risk: ${customer.risk}`} icon="chart" tone="violet" />
      <KpiCard label="Oldest overdue" value={`${customer.oldest_days_overdue}d`} caption={`Due ${fmt(customer.oldest_due_date)}`} icon="calendar" tone="rose" />
    </div>
    <div className="dashboard-grid">
      <Card>
        <SectionHeading title="Rule-based assessment" description="Backend-derived facts; not recalculated by the frontend." />
        <div className="fact-list">
          <div><span>Priority</span><strong><StatusBadge value={customer.priority} toneMap={{ low: 'green', medium: 'blue', high: 'amber', critical: 'rose' }} /></strong></div>
          <div><span>Credit utilization</span><strong>{creditUtilization}</strong></div>
          <div><span>Recommended action</span><strong>{customer.recommended_action}</strong></div>
        </div>
        <div className="reason-list">{(customer.priority_reasons || []).map((reason) => <div key={reason}><Icon name="check" size={14} />{reason}</div>)}</div>
      </Card>
      <Card>
        <SectionHeading title="AI-generated explanation" description="Populated only when the Collections Agent is explicitly run." />
        {agentResult ? (agentResult.decisions || []).map((decision, index) => <div className="ai-explanation" key={decision.decision_id || `${decision.summary}-${index}`}>
          <div className="decision-title"><StatusBadge value={decision.risk_level} toneMap={{ low: 'green', medium: 'blue', high: 'amber', critical: 'rose' }} /><h3>{decision.summary}</h3></div>
          <p>{decision.reasoning}</p>
          <small>Confidence: {decision.confidence ? formatPercent(Number(decision.confidence.value) * 100, 0) : '—'}</small>
        </div>) : <EmptyState title="No AI explanation yet" description="Run the Collections Agent to generate an explanation alongside deterministic customer facts." />}
      </Card>
    </div>
    <Card>
      <SectionHeading title="Exposure by currency" description="Each balance comes from the backend. No foreign-exchange conversion is configured." />
      {balances.length ? <div className="exposure-list">{balances.map((balance) => <div className="exposure-line" key={balance.currency}>
        <span>{balance.currency} · {balance.open_invoice_count} open invoice(s)</span>
        <strong>{formatMoney(balance.total_outstanding, balance.currency)}</strong>
        <em>{formatMoney(balance.overdue_amount, balance.currency)} overdue</em>
      </div>)}</div> : <EmptyState title="No open currency balances" description="No positive outstanding invoices were found for this customer." />}
    </Card>
  </div>
}
