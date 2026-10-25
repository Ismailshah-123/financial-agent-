import { useState, type FormEvent, type ReactElement } from 'react'
import { api } from '../api'
import { ApiErrorBanner, Button, Card, ConfirmDialog, Field, LoadingPanel, Notice, PageHeader, RISK_TONES, SectionHeading, StatusBadge } from '../components/ui'
import { formatDateTime, formatLabel } from '../formatters'
import { useAsync } from '../hooks'
import type { SapStatus, SapVerification, SapVerificationState } from '../types'

const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/

interface StateInfo { title: string; tone: string; notice: 'success' | 'warning' | 'info'; guidance: string }

const STATES: Record<SapVerificationState, StateInfo> = {
  disabled: { title: 'Integration disabled', tone: 'neutral', notice: 'info', guidance: 'SAP integration is switched off on the server (SAP_ENABLED).' },
  not_configured: { title: 'Not configured', tone: 'amber', notice: 'warning', guidance: 'Service Layer URL, company database or credentials are missing on the server.' },
  configuration_invalid: { title: 'Configuration invalid', tone: 'rose', notice: 'warning', guidance: 'The configuration was rejected before any connection was attempted. Check the Service Layer URL and TLS settings.' },
  connection_unreachable: { title: 'Service Layer unreachable', tone: 'rose', notice: 'warning', guidance: 'The server could not reach the Service Layer, or the TLS certificate was not accepted. Certificate checks are never disabled.' },
  authentication_failed: { title: 'Authentication failed', tone: 'rose', notice: 'warning', guidance: 'The Service Layer was reached but rejected the credentials or company database.' },
  authenticated_and_reachable: { title: 'Authenticated, read check incomplete', tone: 'amber', notice: 'warning', guidance: 'Login worked but the read check did not finish. This is not proof the integration works.' },
  read_only_verification_failed: { title: 'Read check failed', tone: 'rose', notice: 'warning', guidance: 'Login worked but reading business partners failed. Do not run synchronization until this passes.' },
  read_only_verification_passed: { title: 'Read check passed', tone: 'green', notice: 'success', guidance: 'A real read from SAP succeeded. This proves connectivity and read access only; it does not prove that writing documents works.' },
}

interface RunResult {
  run_id: string
  status: string
  agent_type: string
  error_message?: string | null
  decisions?: { decision_id?: string; risk_level: string; summary: string; reasoning: string }[]
}

export default function SapIntegration({ can }: { can: (permission: string) => boolean }): ReactElement {
  const canConfigure = can('agent:configure')
  const status = useAsync((signal) => api.get<SapStatus>('/sap/status', undefined, signal), [])
  const [verification, setVerification] = useState<SapVerification | null>(null)
  const [verifyError, setVerifyError] = useState<unknown>(null)
  const [verifying, setVerifying] = useState(false)

  const [entityType, setEntityType] = useState('')
  const [entityId, setEntityId] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncError, setSyncError] = useState<unknown>(null)
  const [result, setResult] = useState<RunResult | null>(null)

  const supported = status.data?.supported_entities ?? []
  const selectedType = entityType || supported[0] || ''
  const idValid = UUID.test(entityId.trim())
  const enabled = Boolean(status.data?.enabled)

  async function verify(): Promise<void> {
    setVerifying(true)
    setVerification(null)
    setVerifyError(null)
    try {
      setVerification(await api.post<SapVerification>('/sap/verify', {}))
    } catch (error) {
      setVerifyError(error)
    } finally {
      setVerifying(false)
    }
  }

  function requestSync(event: FormEvent): void {
    event.preventDefault()
    if (!canConfigure || !idValid || !selectedType) return
    setSyncError(null)
    setConfirmOpen(true)
  }

  async function runSync(): Promise<void> {
    if (syncing) return
    setSyncing(true)
    setSyncError(null)
    try {
      setResult(await api.post<RunResult>('/agents/sap-integration/run', { entity_type: selectedType, entity_id: entityId.trim() }))
      setConfirmOpen(false)
    } catch (error) {
      setSyncError(error)
    } finally {
      setSyncing(false)
    }
  }

  const info = verification ? STATES[verification.state] : null

  // Each rung only reports what the server has actually told us.
  const ladder: { label: string; state: 'done' | 'pending' | 'unknown' | 'blocked'; detail: string }[] = [
    { label: 'Enabled on the server', state: !status.data ? 'unknown' : status.data.enabled ? 'done' : 'blocked', detail: status.data ? (status.data.enabled ? 'SAP_ENABLED is on' : 'SAP_ENABLED is off') : 'Checking' },
    { label: 'Configuration present', state: !status.data ? 'unknown' : status.data.configured ? 'done' : 'blocked', detail: status.data ? (status.data.configured ? 'URL, company database and credentials set' : 'Something required is missing') : 'Checking' },
    { label: 'Service Layer reachable and signed in', state: !verification ? 'pending' : ['authenticated_and_reachable', 'read_only_verification_failed', 'read_only_verification_passed'].includes(verification.state) ? 'done' : 'blocked', detail: verification ? STATES[verification.state].title : 'Run the read only check' },
    { label: 'Read of business partners verified', state: !verification ? 'pending' : verification.state === 'read_only_verification_passed' ? 'done' : 'blocked', detail: verification?.state === 'read_only_verification_passed' ? `Verified ${formatDateTime(verification.verified_at ?? verification.checked_at)}` : 'Not verified' },
    { label: 'Synchronization status and reconciliation', state: 'unknown', detail: 'Not reported by the backend yet; results appear only in the run output below.' },
  ]

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Integration layer" title="SAP Business One" description="Controlled access to the SAP Service Layer through the finance server. This browser never talks to SAP and never sees SAP credentials." />

      <Card>
        <SectionHeading title="Integration readiness" description="Configuration is shown separately from live connection evidence." />
        {status.error ? <ApiErrorBanner error={status.error} title="SAP status could not be loaded" onRetry={status.reload} />
          : !status.data ? <LoadingPanel label="Loading SAP status…" />
          : <ol className="ladder">{ladder.map((step) => (
            <li key={step.label} className={`ladder-${step.state}`}>
              <span className="ladder-mark" aria-hidden="true">{step.state === 'done' ? '✓' : step.state === 'blocked' ? '✕' : '·'}</span>
              <div><strong>{step.label}</strong><span>{step.detail}</span></div>
              <StatusBadge value={step.state === 'done' ? 'confirmed' : step.state === 'blocked' ? 'not met' : step.state === 'pending' ? 'not checked' : 'unknown'} toneMap={{ confirmed: 'green', 'not met': 'amber', 'not checked': 'neutral', unknown: 'neutral' }} />
            </li>
          ))}</ol>}
        <div className="action-row">
          <Button type="button" icon="plug" disabled={verifying || !enabled} onClick={() => void verify()}>{verifying ? 'Verifying read only connection…' : 'Verify read only connection'}</Button>
          {status.data && !enabled && <span className="muted-label">Enable SAP on the server to run the check.</span>}
        </div>
        {verifyError !== null && <ApiErrorBanner error={verifyError} title="Verification request failed" />}
        {verification && info && (
          <Notice tone={info.notice} icon={info.notice === 'success' ? 'check' : 'alert'} live="status">
            <strong>{info.title}.</strong> {info.guidance} <small className="reference">Checked {formatDateTime(verification.checked_at)} · Correlation ID {verification.correlation_id}{verification.records_returned != null ? ` · ${verification.records_returned} business partner(s) read` : ''}</small>
          </Notice>
        )}
      </Card>

      <Card>
        <SectionHeading title="Master data synchronization" description="Sends one customer or vendor from this platform to SAP." />
        {!canConfigure ? (
          <Notice tone="info" icon="lock" live="none">Your role can check connectivity but cannot run synchronization. That needs the agent:configure permission.</Notice>
        ) : (
          <form className="agent-form" onSubmit={requestSync}>
            <Field label="Record type">
              <select required value={selectedType} onChange={(e) => setEntityType(e.target.value)}>
                {supported.map((type) => <option key={type} value={type}>{formatLabel(type)}</option>)}
              </select>
            </Field>
            <Field label="Record ID" hint={entityId && !idValid ? 'Enter the record UUID, for example 3f2b8c1e-5d4a-4b7e-9a10-0c2d3e4f5a6b.' : 'The platform UUID of the customer or vendor.'}>
              <input required value={entityId} aria-invalid={entityId !== '' && !idValid} placeholder="00000000-0000-0000-0000-000000000000" onChange={(e) => setEntityId(e.target.value)} />
            </Field>
            <Notice tone="warning" icon="alert" live="none">This writes to SAP. Use an approved test company until a controlled live verification has been completed. Invoices, payments and other financial documents cannot be sent from this screen.</Notice>
            <Button type="submit" icon="arrow" disabled={syncing || !enabled || !idValid || !selectedType}>Review and run synchronization</Button>
          </form>
        )}
        {result && (
          <div className="sync-result">
            <div className="decision-grid">
              <div><span>Status</span><strong>{formatLabel(result.status)}</strong></div>
              <div><span>Decisions</span><strong>{result.decisions?.length ?? 0}</strong></div>
              <div><span>Run</span><strong>{String(result.run_id).slice(0, 12)}</strong></div>
            </div>
            {result.error_message && <Notice tone="warning" icon="alert" live="alert">{result.error_message}</Notice>}
            {(result.decisions ?? []).map((d, i) => (
              <div className="result-decision" key={d.decision_id ?? i}>
                <div className="decision-title"><StatusBadge value={d.risk_level} toneMap={RISK_TONES} /><h3>{d.summary}</h3></div>
                <p>{d.reasoning}</p>
              </div>
            ))}
            <Notice tone="info" icon="lock" live="none">This is the agent's report of the run. If a result is unclear, check the record in SAP before running it again; repeated runs are not guaranteed to be harmless.</Notice>
          </div>
        )}
      </Card>

      <Card>
        <SectionHeading title="What this screen can do" description="Supported interactive scope, taken from the backend." />
        <div className="sap-entities">
          {supported.map((type) => <div key={type}><span className="entity-dot" aria-hidden="true" /><strong>{formatLabel(type)}</strong><StatusBadge value="master data" toneMap={{ 'master data': 'blue' }} /></div>)}
        </div>
        <Notice tone="info" icon="lock" live="none">Mapping code for documents and payments exists in the repository but is not exposed here until approval, duplicate control and reconciliation are in place. No live SAP company has been verified by this software.</Notice>
      </Card>

      <ConfirmDialog
        open={confirmOpen}
        title="Run SAP synchronization?"
        confirmLabel="Run synchronization"
        tone="danger"
        busy={syncing}
        onConfirm={() => void runSync()}
        onCancel={() => { if (!syncing) setConfirmOpen(false) }}
      >
        <p>You are about to send <strong>{formatLabel(selectedType)}</strong> <code>{entityId.trim()}</code> to SAP.</p>
        <p>The server creates or compares the matching business partner in the configured company database. Confirm it is the intended company before continuing.</p>
        {syncError !== null && <ApiErrorBanner error={syncError} title="Synchronization did not complete" />}
        <p className="muted-label">If this request times out, the outcome is unknown. Check SAP before trying again.</p>
      </ConfirmDialog>
    </div>
  )
}
