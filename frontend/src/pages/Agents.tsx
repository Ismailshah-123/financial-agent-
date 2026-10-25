import { useEffect, useMemo, useState, type FormEvent, type ReactElement } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icons'
import {
  ApiErrorBanner, Button, Card, EmptyState, Field, Notice, PageHeader, RISK_TONES, SectionHeading, Skeleton, StatusBadge,
} from '../components/ui'
import { formatLabel, formatMoney, formatNumber, formatPercent, localDateInputValue } from '../formatters'
import { useAsync } from '../hooks'
import type { AgentCatalogItem, AgentRunResult } from '../types'

type FormValues = Record<string, string>

export default function Agents(): ReactElement {
  const catalog = useAsync((signal) => api.get<AgentCatalogItem[]>('/agents/catalog', undefined, signal), [])
  const [selected, setSelected] = useState('finance_director')
  const [form, setForm] = useState<FormValues>({})
  const [result, setResult] = useState<AgentRunResult | null>(null)
  const [runError, setRunError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const items = catalog.data ?? []
  const agent = useMemo(() => items.find((item) => item.key === selected) ?? items[0], [items, selected])

  // Start each agent from its own contract: required selects get their first option, optional dates today.
  useEffect(() => {
    if (!agent) return
    const initial: FormValues = {}
    for (const field of agent.input_fields) {
      if (field.kind === 'date' && !field.required) initial[field.name] = localDateInputValue()
      if (field.kind === 'select' && field.options.length) initial[field.name] = field.options[0]
    }
    setForm(initial)
    setResult(null)
    setRunError(null)
  }, [agent?.key])

  async function run(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (!agent || busy) return
    setBusy(true)
    setRunError(null)
    setResult(null)
    const payload: Record<string, string | number> = {}
    for (const field of agent.input_fields) {
      const raw = form[field.name]
      if (raw === '' || raw === undefined) continue
      payload[field.name] = field.kind === 'number' ? Number(raw) : raw
    }
    try {
      setResult(await api.post<AgentRunResult>(agent.endpoint, payload))
    } catch (error) {
      setRunError(error)
    } finally {
      setBusy(false)
    }
  }

  const header = (
    <PageHeader
      eyebrow="AI decision layer"
      title="AI Agent Center"
      description="Run the exact request contracts exposed by the backend. The catalog is generated from the server side Pydantic schemas, so the UI does not guess fields or enums."
      action={<button type="button" className="icon-button" onClick={catalog.reload} aria-label="Refresh agent contracts" title="Refresh agent contracts"><Icon name="refresh" size={17} /></button>}
    />
  )

  if (catalog.error && !catalog.data) {
    return <div className="page-stack">{header}<ApiErrorBanner error={catalog.error} title="Agent catalog unavailable" onRetry={catalog.reload} /></div>
  }
  if (!catalog.data) return <div className="page-stack">{header}<Skeleton lines={5} label="Loading agent contracts" /></div>
  if (!agent) {
    return <div className="page-stack">{header}<EmptyState title="No agents available to your role" description="Your current role cannot run any backend agent. Ask an administrator if you need access." /></div>
  }

  return (
    <div className="page-stack">
      {header}
      <div className="agent-layout">
        <Card className="agent-catalog">
          <SectionHeading title="Operational agents" description={`${items.length} runnable backend workflows.`} />
          <div className="agent-list">
            {items.map((item) => (
              <button key={item.key} type="button" aria-pressed={item.key === agent.key} className={item.key === agent.key ? 'selected' : ''} onClick={() => setSelected(item.key)}>
                <span className="agent-node"><Icon name={item.key === 'sap_integration' ? 'plug' : 'bot'} size={16} /></span>
                <span><strong>{item.name}</strong><small>{item.description}</small></span>
                <Icon name="chevron" size={14} />
              </button>
            ))}
          </div>
        </Card>
        <div className="agent-workspace">
          <Card>
            <div className="workspace-heading">
              <div><div className="eyebrow">{formatLabel(agent.key)}</div><h2>{agent.name}</h2><p>{agent.description}</p></div>
              <StatusBadge value="ready" toneMap={{ ready: 'green' }} />
            </div>
            <form className="agent-form" onSubmit={(event) => void run(event)}>
              {agent.input_fields.map((field) => (
                <Field key={field.name} label={field.label} hint={field.description || (field.kind === 'uuid' ? 'The backend expects a UUID.' : undefined)}>
                  {field.kind === 'select'
                    ? <select required={field.required} value={form[field.name] ?? ''} onChange={(event) => setForm((current) => ({ ...current, [field.name]: event.target.value }))}>{field.options.map((option) => <option key={option} value={option}>{formatLabel(option)}</option>)}</select>
                    : <input
                      required={field.required}
                      type={field.kind === 'number' ? 'number' : field.kind === 'date' ? 'date' : 'text'}
                      min={field.kind === 'number' ? 1 : undefined}
                      value={form[field.name] ?? ''}
                      placeholder={field.kind === 'uuid' ? '00000000-0000-0000-0000-000000000000' : ''}
                      onChange={(event) => setForm((current) => ({ ...current, [field.name]: event.target.value }))}
                    />}
                </Field>
              ))}
              {runError !== null && <ApiErrorBanner error={runError} title="The agent run did not complete" />}
              <div className="form-foot">
                <Notice tone="info" icon="lock" live="none">Agent execution produces recommendations. It does not bypass human approval controls or directly transact unless a separately authorized execution endpoint is used.</Notice>
                <Button type="submit" icon="arrow" disabled={busy}>{busy ? 'Running agent…' : 'Run agent'}</Button>
              </div>
            </form>
          </Card>
          {result ? <AgentResult result={result} /> : <Card><EmptyState title="No run selected" description="Run the selected backend agent to inspect its decision envelope, confidence, evidence, risk and approval state." /></Card>}
        </div>
      </div>
    </div>
  )
}

function AgentResult({ result }: { result: AgentRunResult }): ReactElement {
  return (
    <Card className="agent-result">
      <SectionHeading title="Run result" description={`Run ${String(result.run_id).slice(0, 12)}… · ${formatNumber(result.duration_ms ?? 0)} ms`} />
      <div className="decision-grid">
        <div><span>Status</span><strong>{formatLabel(result.status)}</strong></div>
        <div><span>Decisions</span><strong>{result.decisions?.length ?? 0}</strong></div>
        <div><span>Agent</span><strong>{formatLabel(result.agent_type)}</strong></div>
      </div>
      {result.error_message && <Notice tone="warning" icon="alert" live="alert">{result.error_message}</Notice>}
      {(result.decisions ?? []).map((decision, index) => (
        <div className="result-decision" key={decision.decision_id ?? index}>
          <div className="decision-title"><StatusBadge value={decision.risk_level} toneMap={RISK_TONES} /><h3>{decision.summary}</h3></div>
          <p>{decision.reasoning}</p>
          <div className="decision-grid">
            <div><span>Confidence</span><strong>{decision.confidence ? formatPercent(Number(decision.confidence.value) * 100, 0) : '—'}</strong></div>
            <div><span>Approval required</span><strong>{decision.requires_approval ? 'Yes' : 'No'}</strong></div>
            <div><span>Financial impact</span><strong>{decision.financial_impact ? formatMoney(decision.financial_impact.amount, decision.financial_impact.currency) : '—'}</strong></div>
          </div>
          {(decision.supporting_evidence?.length ?? 0) > 0 && (
            <div className="evidence">{decision.supporting_evidence?.map((evidence, evidenceIndex) => <div key={evidenceIndex}><Icon name="file" size={14} />{formatLabel(evidence.document_type)} · {evidence.document_id}</div>)}</div>
          )}
        </div>
      ))}
    </Card>
  )
}
