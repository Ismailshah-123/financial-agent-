import { useState, type ReactElement } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icons'
import {
  ApiErrorBanner, Button, Card, ConfirmDialog, EmptyState, Field, LoadingPanel, Notice, PageHeader, RISK_TONES, StatusBadge, Tabs,
} from '../components/ui'
import { formatDate, formatDateTime, formatLabel, formatMoney, formatPercent } from '../formatters'
import { useAsync } from '../hooks'
import type { ApprovalRequest, ApprovalSummary, ApprovalView } from '../types'

const PAGE_SIZE = 25
const AGENTS = ['collections', 'accounts_payable', 'accounts_receivable', 'treasury', 'fraud_detection', 'budget_planning', 'compliance', 'finance_director', 'bank_reconciliation', 'tax']

const VIEW_COPY: Record<string, { label: string; empty: string; help: string }> = {
  pending: { label: 'Pending', empty: 'No requests are waiting for a decision.', help: 'Recommendations waiting for a human decision. Approving records the decision only.' },
  awaiting_execution: { label: 'Awaiting execution', empty: 'No approved actions are waiting to be executed.', help: 'Approved and executable. Nothing has happened to the underlying record yet.' },
  executing: { label: 'In progress', empty: 'Nothing is currently executing.', help: 'Marked as executing by the server. A request that stays here has to be reconciled, not retried.' },
  failed: { label: 'Failed', empty: 'No executions have failed.', help: 'Execution failed. Review the error and the underlying record before trying again.' },
  executed: { label: 'Executed', empty: 'No actions have been executed yet.', help: 'History of executed actions with their recorded results.' },
  rejected: { label: 'Rejected', empty: 'No requests have been rejected.', help: 'History of rejected recommendations.' },
}

type DialogState =
  | { kind: 'approve'; item: ApprovalRequest }
  | { kind: 'reject'; item: ApprovalRequest }
  | { kind: 'execute'; item: ApprovalRequest }
  | null

export default function Approvals({ can }: { can: (permission: string) => boolean }): ReactElement {
  const [view, setView] = useState<ApprovalView>('pending')
  const [agent, setAgent] = useState('')
  const [offset, setOffset] = useState(0)
  const [dialog, setDialog] = useState<DialogState>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)
  const [message, setMessage] = useState('')

  const summary = useAsync((signal) => api.get<ApprovalSummary>('/approval-requests/summary', undefined, signal), [])
  const list = useAsync(
    (signal) => api.get<ApprovalRequest[]>('/approval-requests', { view, agent_type: agent || undefined, offset, limit: PAGE_SIZE }, signal),
    [view, agent, offset],
  )

  const canAct = can('approval_request:action')
  const canExecute = canAct && can('payment:approve')
  const counts: Record<string, number | undefined> = { pending: summary.data?.pending, awaiting_execution: summary.data?.awaiting_execution, executing: summary.data?.executing, failed: summary.data?.failed }

  const tabs = Object.entries(VIEW_COPY).map(([key, copy]) => ({
    key,
    label: counts[key] === undefined ? copy.label : `${copy.label} (${counts[key]})`,
  }))

  function openDialog(next: DialogState): void {
    setNote('')
    setActionError(null)
    setDialog(next)
  }

  function closeDialog(): void {
    if (busy) return
    setDialog(null)
  }

  async function perform(): Promise<void> {
    if (!dialog || busy) return
    const { kind, item } = dialog
    setBusy(true)
    setActionError(null)
    try {
      if (kind === 'approve') {
        await api.post<ApprovalRequest>(`/approval-requests/${item.id}/approve`, { notes: note.trim() || null })
        setMessage('Approval recorded. The underlying action has not been executed.')
      } else if (kind === 'reject') {
        await api.post<ApprovalRequest>(`/approval-requests/${item.id}/reject`, { reason: note.trim() })
        setMessage('Recommendation rejected and written to the audit trail.')
      } else {
        // The key matches the one the server derives, so a retry after a token
        // renewal is safe to replay: the backend executes each key at most once.
        const key = item.idempotency_key || `approval:${item.id}:execute`
        const result = await api.post<ApprovalRequest>(`/approval-requests/${item.id}/execute`, undefined, { 'Idempotency-Key': key })
        setMessage(result.execution_status === 'executed'
          ? 'Execution completed. The recorded result is attached to the request.'
          : `Execution finished with status: ${formatLabel(result.execution_status)}.`)
      }
      setDialog(null)
      list.reload()
      summary.reload()
    } catch (error) {
      setActionError(error)
      // A failed or ambiguous execution may have changed server state; show the truth.
      if (kind === 'execute') { list.reload(); summary.reload() }
    } finally {
      setBusy(false)
    }
  }

  function changeView(next: string): void {
    setView(next as ApprovalView)
    setOffset(0)
    setMessage('')
  }

  const items = list.data ?? []
  const hasNext = items.length === PAGE_SIZE
  const copy = VIEW_COPY[view]

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Human in the loop"
        title="Approval inbox"
        description="Review AI recommendations with their reasoning, evidence, confidence and financial impact. Approving a recommendation and executing its action are separate steps with separate permissions."
        action={<button type="button" className="icon-button" onClick={() => { list.reload(); summary.reload() }} aria-label="Refresh approval queue" title="Refresh approval queue"><Icon name="refresh" size={17} /></button>}
      />
      {message && <Notice tone="success" live="status">{message}</Notice>}
      {summary.data && summary.data.failed > 0 && view !== 'failed' && (
        <Notice tone="warning" icon="alert" live="none">{summary.data.failed} approved action(s) failed to execute. Open the Failed tab to review them.</Notice>
      )}

      <Card>
        <Tabs label="Approval views" items={tabs} value={view} onChange={changeView} />
        <p className="view-help">{copy.help}</p>
        <div className="filter-row">
          <Field label="Agent">
            <select value={agent} onChange={(e) => { setAgent(e.target.value); setOffset(0) }}>
              <option value="">All agents</option>
              {AGENTS.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
            </select>
          </Field>
          <div className="approval-policy"><Icon name="lock" size={15} /><span>Approval and execution are separate server side controls. Approving a recommendation never sends money or posts a journal.</span></div>
        </div>
      </Card>

      {list.error ? <ApiErrorBanner error={list.error} title="Approvals could not be loaded" onRetry={list.reload} />
        : list.data === null ? <LoadingPanel label="Loading approval queue…" />
        : items.length === 0 ? <EmptyState title={offset > 0 ? 'No more requests' : 'Nothing here'} description={copy.empty} />
        : <div className="approval-stack">{items.map((item) => (
          <ApprovalCard key={item.id} item={item} canAct={canAct} canExecute={canExecute} onOpen={openDialog} />
        ))}</div>}

      {list.data !== null && (offset > 0 || hasNext) && (
        <nav className="pagination" aria-label="Pagination">
          <span aria-live="polite">Showing {offset + 1} to {offset + items.length}</span>
          <div>
            <button type="button" disabled={list.loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
            <button type="button" disabled={list.loading || !hasNext} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button>
          </div>
        </nav>
      )}

      <ConfirmDialog
        open={dialog?.kind === 'approve'}
        title="Approve this recommendation?"
        confirmLabel="Record approval"
        busy={busy}
        onConfirm={() => void perform()}
        onCancel={closeDialog}
      >
        {dialog?.kind === 'approve' && <>
          <p><strong>{dialog.item.summary}</strong></p>
          <p>This records your decision only. It does not execute the underlying action or post anything to SAP.</p>
          <Field label="Reviewer note (optional)" hint="Saved with the decision in the audit trail.">
            <textarea rows={3} value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
          </Field>
          {actionError !== null && <ApiErrorBanner error={actionError} title="Approval was not recorded" />}
        </>}
      </ConfirmDialog>

      <ConfirmDialog
        open={dialog?.kind === 'reject'}
        title="Reject this recommendation?"
        confirmLabel="Reject recommendation"
        tone="danger"
        busy={busy}
        confirmDisabled={!note.trim()}
        onConfirm={() => void perform()}
        onCancel={closeDialog}
      >
        {dialog?.kind === 'reject' && <>
          <p><strong>{dialog.item.summary}</strong></p>
          <Field label="Reason (required)" hint="Written to the approval audit trail.">
            <textarea rows={3} value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
          </Field>
          {actionError !== null && <ApiErrorBanner error={actionError} title="Rejection was not recorded" />}
        </>}
      </ConfirmDialog>

      <ConfirmDialog
        open={dialog?.kind === 'execute'}
        title="Execute this approved action?"
        confirmLabel="Execute action"
        tone="danger"
        busy={busy}
        onConfirm={() => void perform()}
        onCancel={closeDialog}
      >
        {dialog?.kind === 'execute' && <>
          <p><strong>{dialog.item.summary}</strong></p>
          <dl className="dialog-facts">
            <div><dt>Action</dt><dd>{dialog.item.action_type ? formatLabel(dialog.item.action_type) : '—'}</dd></div>
            <div><dt>Financial impact</dt><dd>{dialog.item.decision.financial_impact ? formatMoney(dialog.item.decision.financial_impact.amount, dialog.item.decision.financial_impact.currency) : 'Not stated'}</dd></div>
            <div><dt>Idempotency key</dt><dd><code>{dialog.item.idempotency_key || `approval:${dialog.item.id}:execute`}</code></dd></div>
          </dl>
          <p>This can change financial state and cannot be undone from this screen. The server runs each key at most once. This screen reports what the server returns and does not assume an SAP document was created.</p>
          {actionError !== null && <ApiErrorBanner error={actionError} title="Execution did not complete" />}
        </>}
      </ConfirmDialog>
    </div>
  )
}

interface CardProps {
  item: ApprovalRequest
  canAct: boolean
  canExecute: boolean
  onOpen: (state: DialogState) => void
}

function ApprovalCard({ item, canAct, canExecute, onOpen }: CardProps): ReactElement {
  const decision = item.decision || {}
  const impact = decision.financial_impact
  const executable = Boolean(item.action_type)
  const result = item.execution_result
    ? Object.entries(item.execution_result).filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value)).slice(0, 8)
    : []

  return (
    <Card className="approval-card">
      <div className="approval-head">
        <div>
          <div className="eyebrow">{formatLabel(item.agent_type)}</div>
          <h2>{item.summary}</h2>
          <p>Created {formatDate(item.created_at)} · Request {String(item.id).slice(0, 8)}</p>
        </div>
        <StatusBadge value={item.risk_level} toneMap={RISK_TONES} />
      </div>
      <div className="decision-grid">
        <div><span>Financial impact</span><strong>{impact ? formatMoney(impact.amount, impact.currency) : 'No direct amount'}</strong></div>
        <div><span>Confidence</span><strong>{decision.confidence ? formatPercent(Number(decision.confidence.value) * 100, 0) : 'Not provided'}</strong></div>
        <div><span>Rollback</span><strong>{decision.rollback_strategy?.is_reversible ? 'Reversible' : 'Manual or irreversible'}</strong></div>
      </div>
      <div className="decision-section"><h3>Reasoning</h3><p>{decision.reasoning || 'No reasoning was returned.'}</p></div>
      {(decision.supporting_evidence ?? []).length > 0 && (
        <div className="evidence"><h3>Evidence</h3>{decision.supporting_evidence!.map((e, i) => <div key={`${e.document_id}-${i}`}><Icon name="file" size={15} /><span>{formatLabel(e.document_type)} · {e.document_id}</span></div>)}</div>
      )}
      {(decision.relevant_policies ?? []).length > 0 && (
        <div className="policy-list"><span>Policies checked</span>{decision.relevant_policies!.map((p) => <em key={p}>{p}</em>)}</div>
      )}
      <div className="decision-grid execution-state">
        <div><span>Approval status</span><strong>{formatLabel(item.status)}</strong></div>
        <div><span>Action</span><strong>{item.action_type ? formatLabel(item.action_type) : 'Review only'}</strong></div>
        <div><span>Execution</span><strong>{formatLabel(item.execution_status)}</strong></div>
      </div>
      {item.resolution_notes && <p className="resolution-note"><strong>{item.status === 'rejected' ? 'Rejection reason' : 'Reviewer note'}:</strong> {item.resolution_notes}</p>}
      {item.executed_at && <p className="resolution-note">Executed {formatDateTime(item.executed_at)}</p>}
      {result.length > 0 && (
        <dl className="dialog-facts">{result.map(([key, value]) => <div key={key}><dt>{formatLabel(key)}</dt><dd>{String(value)}</dd></div>)}</dl>
      )}
      {item.execution_error && <div className="inline-error" role="alert"><Icon name="alert" size={16} />{item.execution_error}</div>}

      {item.status === 'approved' && executable && item.execution_status === 'executing' && (
        <Notice tone="warning" icon="alert" live="none">The server marked this action as executing. If it stays this way, do not retry: check the payment record and reconcile it first.</Notice>
      )}
      {item.status === 'approved' && executable && item.execution_status === 'failed' && (
        <Notice tone="warning" icon="alert" live="none">Execution failed. Check the underlying record before executing again; the server will not run the same key twice once it succeeds.</Notice>
      )}

      {!canAct ? (
        <Notice tone="info" icon="lock" live="none">You have read access only. The approval_request:action permission is required to resolve this request.</Notice>
      ) : (
        <div className="action-row">
          {item.status === 'pending' && <>
            <Button variant="primary" icon="check" onClick={() => onOpen({ kind: 'approve', item })}>Approve recommendation</Button>
            <Button variant="secondary" icon="x" onClick={() => onOpen({ kind: 'reject', item })}>Reject</Button>
          </>}
          {item.status === 'approved' && executable && ['execution_pending', 'failed'].includes(item.execution_status) && (
            canExecute
              ? <Button variant="primary" icon="arrow" onClick={() => onOpen({ kind: 'execute', item })}>{item.execution_status === 'failed' ? 'Retry execution' : 'Execute approved action'}</Button>
              : <Notice tone="info" icon="lock" live="none">Approval recorded. A user with the payment:approve permission must execute this action.</Notice>
          )}
        </div>
      )}
    </Card>
  )
}
