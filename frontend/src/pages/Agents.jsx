import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icons'
import { Button, Card, Field, PageHeader, SectionHeading, StatusBadge, EmptyState, LoadingPanel } from '../components/ui'

const today = () => new Date().toISOString().slice(0, 10)
import { formatMoney as money, formatLabel as label, formatNumber, formatPercent } from '../formatters'

export default function Agents() {
  const [catalog, setCatalog] = useState(null)
  const [selected, setSelected] = useState('finance_director')
  const [form, setForm] = useState({})
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function loadCatalog() {
    setError('')
    try {
      setCatalog(await api.get('/agents/catalog'))
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => { loadCatalog() }, [])

  const agent = useMemo(() => catalog?.find((item) => item.key === selected) || catalog?.[0], [catalog, selected])

  useEffect(() => {
    if (!agent) return
    const initial = {}
    for (const field of agent.input_fields) {
      if (field.kind === 'date' && !field.required) initial[field.name] = today()
      if (field.kind === 'select' && field.options.length) initial[field.name] = field.options[0]
    }
    setForm(initial)
    setResult(null)
    setError('')
  }, [agent])

  function selectAgent(key) { setSelected(key) }
  function setField(key, value) { setForm((current) => ({ ...current, [key]: value })) }

  async function run(event) {
    event.preventDefault()
    if (!agent) return
    setBusy(true)
    setError('')
    setResult(null)
    const payload = {}
    for (const field of agent.input_fields) {
      const raw = form[field.name]
      if (raw === '' || raw === undefined || raw === null) continue
      payload[field.name] = field.kind === 'number' ? Number(raw) : raw
    }
    try {
      setResult(await api.post(agent.endpoint, payload))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!catalog && !error) return <LoadingPanel label="Loading agent contracts…" />
  if (error && !catalog) return <div className="page-stack"><PageHeader eyebrow="AI decision layer" title="AI Agent Center" description="Operational agent workflows exposed by the finance API."/><div className="error-banner"><div><strong>Agent catalog unavailable</strong><span>{error}</span></div><button className="button button-secondary" onClick={loadCatalog}>Retry</button></div></div>

  return <div className="page-stack">
    <PageHeader eyebrow="AI decision layer" title="AI Agent Center" description="Run the exact request contracts exposed by the backend. The catalog is generated from the server-side Pydantic schemas, so the UI does not guess fields or enums." action={<button className="icon-button" onClick={loadCatalog} title="Refresh agent contracts"><Icon name="refresh" size={17} /></button>} />
    {error && <div className="inline-error"><Icon name="alert" size={16} />{error}</div>}
    <div className="agent-layout">
      <Card className="agent-catalog"><SectionHeading title="Operational agents" description={`${catalog.length} runnable backend workflows.`} /><div className="agent-list">{catalog.map((item) => <button key={item.key} className={item.key === agent.key ? 'selected' : ''} onClick={() => selectAgent(item.key)}><span className="agent-node"><Icon name={item.key === 'sap_integration' ? 'plug' : 'bot'} size={16} /></span><span><strong>{item.name}</strong><small>{item.description}</small></span><Icon name="chevron" size={14} /></button>)}</div></Card>
      <div className="agent-workspace">
        <Card>
          <div className="workspace-heading"><div><div className="eyebrow">{label(agent.key)}</div><h2>{agent.name}</h2><p>{agent.description}</p></div><StatusBadge value="ready" toneMap={{ ready: 'green' }} /></div>
          <form className="agent-form" onSubmit={run}>
            {agent.input_fields.map((field) => <Field key={field.name} label={field.label} hint={field.description || (field.kind === 'uuid' ? 'Backend expects a UUID.' : '')}>
              {field.kind === 'select' ? <select required={field.required} value={form[field.name] || ''} onChange={(event) => setField(field.name, event.target.value)}>{field.options.map((option) => <option key={option} value={option}>{label(option)}</option>)}</select> : <input required={field.required} type={field.kind === 'number' ? 'number' : field.kind === 'date' ? 'date' : 'text'} min={field.kind === 'number' ? 1 : undefined} value={form[field.name] || ''} placeholder={field.kind === 'uuid' ? '00000000-0000-0000-0000-000000000000' : ''} onChange={(event) => setField(field.name, event.target.value)} />}
            </Field>)}
            <div className="form-foot"><div className="callout info"><Icon name="lock" size={16} /><span>Agent execution produces recommendations. It does not bypass human approval controls or directly transact unless a separately authorized execution endpoint is used.</span></div><Button type="submit" icon="arrow" disabled={busy}>{busy ? 'Running agent…' : 'Run agent'}</Button></div>
          </form>
        </Card>
        {result ? <AgentResult result={result} /> : <Card><EmptyState title="No run selected" description="Run the selected backend agent to inspect its decision envelope, confidence, evidence, risk and approval state." /></Card>}
      </div>
    </div>
  </div>
}

function AgentResult({ result }) {
  return <Card className="agent-result"><SectionHeading title="Run result" description={`Run ${String(result.run_id).slice(0, 12)}… · ${formatNumber(result.duration_ms || 0)} ms`} /><div className="decision-grid"><div><span>Status</span><strong>{label(result.status)}</strong></div><div><span>Decisions</span><strong>{result.decisions?.length || 0}</strong></div><div><span>Agent</span><strong>{label(result.agent_type)}</strong></div></div>{result.error_message && <div className="callout warning"><Icon name="alert" size={16} /><span>{result.error_message}</span></div>}{(result.decisions || []).map((decision, index) => <div className="result-decision" key={decision.decision_id || index}><div className="decision-title"><StatusBadge value={decision.risk_level} toneMap={{ low: 'green', medium: 'blue', high: 'amber', critical: 'rose' }} /><h3>{decision.summary}</h3></div><p>{decision.reasoning}</p><div className="decision-grid"><div><span>Confidence</span><strong>{decision.confidence ? formatPercent(Number(decision.confidence.value) * 100, 0) : '—'}</strong></div><div><span>Approval required</span><strong>{decision.requires_approval ? 'Yes' : 'No'}</strong></div><div><span>Financial impact</span><strong>{decision.financial_impact ? money(decision.financial_impact.amount, decision.financial_impact.currency) : '—'}</strong></div></div>{decision.supporting_evidence?.length > 0 && <div className="evidence">{decision.supporting_evidence.map((evidence, evidenceIndex) => <div key={evidenceIndex}><Icon name="file" size={14} />{label(evidence.document_type)} · {evidence.document_id}</div>)}</div>}</div>)}</Card>
}
