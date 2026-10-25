import { useEffect, useState, type ReactElement } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icons'
import {
  ApiErrorBanner, Button, Card, DataTable, EmptyState, Field, LoadingPanel, Notice, PageHeader, Pagination, SectionHeading, StatusBadge,
} from '../components/ui'
import { formatDateTime, formatLabel } from '../formatters'
import { useAsync, useDebouncedValue } from '../hooks'
import type { AuditLogEntry, AuditVerification, Paginated } from '../types'

const PAGE_SIZE = 50
const OUTCOME_TONES: Record<string, string> = { success: 'green', denied: 'amber', failed: 'rose' }

export default function Audit(): ReactElement {
  const [page, setPage] = useState(1)
  const [actionInput, setActionInput] = useState('')
  const action = useDebouncedValue(actionInput.trim(), 350)
  const [outcome, setOutcome] = useState('')
  const [resourceType, setResourceType] = useState('')
  const [verification, setVerification] = useState<{ result: AuditVerification; checkedAt: string } | null>(null)
  const [verifyError, setVerifyError] = useState<unknown>(null)
  const [verifying, setVerifying] = useState(false)

  useEffect(() => { setPage(1) }, [action, outcome, resourceType])

  const logs = useAsync(
    (signal) => api.get<Paginated<AuditLogEntry>>('/audit/logs', {
      page,
      page_size: PAGE_SIZE,
      action: action || undefined,
      outcome: outcome || undefined,
      resource_type: resourceType || undefined,
    }, signal),
    [page, action, outcome, resourceType],
  )

  // Verification re-reads and re-hashes the whole chain on the server, so it runs on demand
  // rather than on every page load.
  async function verify(): Promise<void> {
    setVerifying(true)
    setVerifyError(null)
    try {
      const result = await api.get<AuditVerification>('/audit/verify')
      setVerification({ result, checkedAt: new Date().toISOString() })
    } catch (error) {
      setVerifyError(error)
    } finally {
      setVerifying(false)
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Audit and control"
        title="Audit Center"
        description="Append only finance activity stored in the database with a hash chain. Entries record who did what, to which record, with what outcome and under which correlation id."
        action={<button type="button" className="icon-button" onClick={logs.reload} aria-label="Refresh audit trail" title="Refresh audit trail"><Icon name="refresh" size={17} /></button>}
      />

      <Card>
        <SectionHeading
          title="Integrity verification"
          description="The server recomputes every entry hash and checks each link to the previous entry. It detects edits or deletions made outside the application. It does not make the log tamper proof: someone with database write access could rewrite the chain and its stored head."
          action={<Button variant="secondary" icon="shield" disabled={verifying} onClick={() => void verify()}>{verifying ? 'Verifying…' : 'Verify chain'}</Button>}
        />
        {verifyError !== null && <ApiErrorBanner error={verifyError} title="Verification could not run" />}
        {verification && (
          <Notice tone={verification.result.valid ? 'success' : 'warning'} icon={verification.result.valid ? 'check' : 'alert'} live={verification.result.valid ? 'status' : 'alert'}>
            {verification.result.valid
              ? `Verified ${verification.result.checked_entries} entries at ${formatDateTime(verification.checkedAt)}.`
              : `${verification.result.message}${verification.result.first_failure_sequence != null ? ` First failure at sequence ${verification.result.first_failure_sequence}.` : ''} Escalate to the security owner and do not alter the log.`}
          </Notice>
        )}
        {!verification && !verifyError && <p className="muted-label">Not checked in this session.</p>}
      </Card>

      <Card>
        <SectionHeading title="Activity" description={logs.data ? `${logs.data.total.toLocaleString('en-US')} matching entries.` : 'Loading entries.'} />
        <div className="filter-bar">
          <Field label="Action contains"><input type="search" value={actionInput} onChange={(e) => setActionInput(e.target.value)} placeholder="approval_request.execute" /></Field>
          <Field label="Outcome">
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="">All outcomes</option>
              <option value="success">Success</option>
              <option value="denied">Denied</option>
              <option value="failed">Failed</option>
            </select>
          </Field>
          <Field label="Resource type"><input type="search" value={resourceType} onChange={(e) => setResourceType(e.target.value)} placeholder="approval_request" /></Field>
        </div>
        {logs.error ? <ApiErrorBanner error={logs.error} title="Audit entries could not be loaded" onRetry={logs.reload} />
          : !logs.data ? <LoadingPanel label="Loading audit trail…" />
          : logs.data.items.length === 0 ? <EmptyState title="No audit entries" description="No entries match the current filters." />
          : <>
            <DataTable<AuditLogEntry>
              ariaLabel="Audit log entries"
              rows={logs.data.items}
              rowKey={(row) => row.id}
              columns={[
                { key: 'created_at', label: 'When', render: (r) => formatDateTime(r.created_at) },
                { key: 'sequence_number', label: 'Seq', numeric: true },
                { key: 'action', label: 'Action', render: (r) => formatLabel(r.action) },
                { key: 'resource_type', label: 'Resource', render: (r) => <><span>{formatLabel(r.resource_type)}</span><small className="cell-sub">{r.resource_id}</small></> },
                { key: 'outcome', label: 'Outcome', render: (r) => <StatusBadge value={r.outcome} toneMap={OUTCOME_TONES} /> },
                { key: 'actor_id', label: 'Actor', render: (r) => <code title={r.actor_id}>{r.actor_id || 'system'}</code> },
                { key: 'correlation_id', label: 'Correlation', render: (r) => <code title={r.correlation_id}>{r.correlation_id || '—'}</code> },
                {
                  key: 'metadata',
                  label: 'Details',
                  render: (r) => (Object.keys(r.metadata || {}).length
                    ? <details><summary>View</summary><pre className="meta-json">{JSON.stringify(r.metadata, null, 2)}</pre></details>
                    : <span className="muted-label">None</span>),
                },
              ]}
            />
            <Pagination page={logs.data.page} pageSize={logs.data.page_size} total={logs.data.total} onPage={setPage} busy={logs.loading} />
          </>}
      </Card>
    </div>
  )
}
