import { useEffect, useId, useRef, type KeyboardEvent, type ReactElement, type ReactNode } from 'react'
import { ApiError } from '../api'
import { Icon } from './Icons'

export type Tone = 'green' | 'blue' | 'amber' | 'rose' | 'violet' | 'neutral'

export function BrandMark({ compact = false }: { compact?: boolean }): ReactElement {
  return (
    <div className={`brand ${compact ? 'brand-compact' : ''}`}>
      <span className="brand-mark" aria-hidden="true">V</span>
      {!compact && <span>Vertex <strong>Finance AI</strong></span>}
    </div>
  )
}

export function Spinner({ size = 18 }: { size?: number }): ReactElement {
  return <span className="spinner" style={{ width: size, height: size }} role="status" aria-label="Loading" />
}

interface PageHeaderProps {
  eyebrow?: string
  title: string
  description?: string
  action?: ReactNode
}

export function PageHeader({ eyebrow, title, description = '', action = null }: PageHeaderProps): ReactElement {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action && <div className="page-header-action">{action}</div>}
    </div>
  )
}

interface KpiCardProps {
  label: string
  value: ReactNode
  caption?: ReactNode
  tone?: string
  icon?: string
}

export function KpiCard({ label, value, caption, tone = 'default', icon }: KpiCardProps): ReactElement {
  return (
    <div className={`kpi-card tone-${tone}`}>
      <div className="kpi-top">
        <span>{label}</span>
        {icon && <span className="kpi-icon"><Icon name={icon} size={17} /></span>}
      </div>
      <div className="kpi-value">{value}</div>
      {caption && <div className="kpi-caption">{caption}</div>}
    </div>
  )
}

interface StatusBadgeProps {
  value: unknown
  toneMap?: Record<string, string>
  fallback?: string
}

/** Colour is never the only signal: the status text is always rendered. */
export function StatusBadge({ value, toneMap = {}, fallback = 'neutral' }: StatusBadgeProps): ReactElement {
  const key = String(value ?? '')
  const tone = toneMap[key] || fallback
  return <span className={`status-badge status-${tone}`}>{(key || 'Unknown').replaceAll('_', ' ')}</span>
}

export const RISK_TONES: Record<string, string> = { low: 'green', medium: 'blue', high: 'amber', critical: 'rose' }

export function EmptyState({ title, description, action = null }: { title: string; description: string; action?: ReactNode }): ReactElement {
  return (
    <div className="empty-state">
      <div className="empty-icon" aria-hidden="true"><Icon name="file" size={22} /></div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  )
}

interface ErrorBannerProps {
  message: string
  title?: string
  /** Shown as a support reference when the server supplied one. */
  correlationId?: string | null
  onRetry?: () => void
}

export function ErrorBanner({ message, title = 'Something needs attention', correlationId, onRetry }: ErrorBannerProps): ReactElement {
  return (
    <div className="error-banner" role="alert">
      <div>
        <strong>{title}</strong>
        <span>{message}</span>
        {correlationId && <small className="reference">Reference: {correlationId}</small>}
      </div>
      {onRetry && (
        <button type="button" className="button button-secondary" onClick={onRetry}>
          <Icon name="refresh" size={16} /> Retry
        </button>
      )}
    </div>
  )
}

/** Renders an ApiError (or any error) as a banner, with the correlation id when known. */
export function ApiErrorBanner({ error, title, onRetry }: { error: unknown; title?: string; onRetry?: () => void }): ReactElement {
  const message = error instanceof Error ? error.message : 'Unexpected error.'
  const correlationId = error instanceof ApiError ? error.correlationId : null
  const retryHint = error instanceof ApiError && error.retryAfterSeconds
    ? ` Try again in ${error.retryAfterSeconds} seconds.`
    : ''
  return <ErrorBanner title={title} message={`${message}${retryHint}`} correlationId={correlationId} onRetry={onRetry} />
}

export function LoadingPanel({ label = 'Loading finance data…' }: { label?: string }): ReactElement {
  return <div className="loading-panel" role="status" aria-live="polite"><Spinner /> <span>{label}</span></div>
}

/** Placeholder shapes shown while data loads. Announced once as busy; the shimmer stops for reduced motion. */
export function Skeleton({ lines = 3, label = 'Loading' }: { lines?: number; label?: string }): ReactElement {
  return (
    <div className="skeleton" role="status" aria-busy="true" aria-label={label}>
      {Array.from({ length: lines }, (_, index) => <span key={index} className="skeleton-line" style={{ width: `${92 - index * 14}%` }} />)}
    </div>
  )
}

export function SkeletonKpis({ count = 4 }: { count?: number }): ReactElement {
  return (
    <div className="kpi-grid" role="status" aria-busy="true" aria-label="Loading figures">
      {Array.from({ length: count }, (_, index) => <div key={index} className="kpi-card skeleton-card"><span className="skeleton-line" style={{ width: '45%' }} /><span className="skeleton-line tall" style={{ width: '70%' }} /><span className="skeleton-line" style={{ width: '55%' }} /></div>)}
    </div>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }): ReactElement {
  return <section className={`card ${className}`}>{children}</section>
}

export function SectionHeading({ title, description = '', action = null }: { title: string; description?: string; action?: ReactNode }): ReactElement {
  return (
    <div className="section-heading">
      <div><h2>{title}</h2>{description && <p>{description}</p>}</div>
      {action}
    </div>
  )
}

export interface Column<Row> {
  key: string
  label: string
  render?: (row: Row) => ReactNode
  /** Right-align numeric columns so digits line up. */
  numeric?: boolean
}

interface DataTableProps<Row> {
  columns: Column<Row>[]
  rows: Row[] | null | undefined
  rowKey?: (row: Row) => string | number
  ariaLabel?: string
  emptyTitle?: string
  emptyDescription?: string
}

/** Scrolls horizontally inside its own region instead of widening the page. The
 * region is focusable so keyboard users can scroll it. */
export function DataTable<Row extends object>({
  columns,
  rows,
  rowKey,
  ariaLabel = 'Finance data table',
  emptyTitle = 'No records found',
  emptyDescription = 'There is nothing to display for the current filters.',
}: DataTableProps<Row>): ReactElement {
  if (!rows?.length) return <EmptyState title={emptyTitle} description={emptyDescription} />
  return (
    <div className="table-wrap" role="region" aria-label={ariaLabel} tabIndex={0}>
      <table>
        <caption className="sr-only">{ariaLabel}</caption>
        <thead>
          <tr>{columns.map((column) => <th key={column.key} scope="col" className={column.numeric ? 'num' : undefined}>{column.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey ? rowKey(row) : index}>
              {columns.map((column) => (
                <td key={column.key} className={column.numeric ? 'num' : undefined}>
                  {column.render ? column.render(row) : String((row as Record<string, unknown>)[column.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ProgressBar({ value, label, right }: { value: number; label: string; right?: ReactNode }): ReactElement {
  const safe = Math.max(0, Math.min(100, Number(value) || 0))
  return (
    <div className="progress-row">
      <div className="progress-label"><span>{label}</span><strong>{right ?? `${safe.toFixed(0)}%`}</strong></div>
      <div className="progress-track" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(safe)}>
        <span style={{ width: `${safe}%` }} />
      </div>
    </div>
  )
}

interface TabsProps {
  items: { key: string; label: string }[]
  value: string
  onChange: (key: string) => void
  label?: string
}

/** WAI-ARIA tabs: roving tabindex with arrow, Home and End key support. */
export function Tabs({ items, value, onChange, label = 'Section tabs' }: TabsProps): ReactElement {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = items.findIndex((item) => item.key === value)
    let next = -1
    if (event.key === 'ArrowRight') next = (index + 1) % items.length
    else if (event.key === 'ArrowLeft') next = (index - 1 + items.length) % items.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = items.length - 1
    if (next < 0) return
    event.preventDefault()
    onChange(items[next].key)
    refs.current[next]?.focus()
  }
  return (
    <div className="tabs" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {items.map((item, index) => {
        const selected = item.key === value
        return (
          <button
            key={item.key}
            ref={(node: HTMLButtonElement | null) => { refs.current[index] = node }}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            className={selected ? 'active' : ''}
            onClick={() => onChange(item.key)}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }): ReactElement {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}

interface ButtonProps {
  children: ReactNode
  variant?: 'primary' | 'secondary' | 'danger'
  icon?: string
  type?: 'button' | 'submit'
  disabled?: boolean
  onClick?: () => void
}

export function Button({ children, variant = 'primary', icon, type = 'button', disabled = false, onClick }: ButtonProps): ReactElement {
  return (
    <button type={type} disabled={disabled} onClick={onClick} className={`button button-${variant}`}>
      {icon && <Icon name={icon} size={16} />} {children}
    </button>
  )
}

/** Inline status message. `role=status` is polite; `alert` interrupts the reader. */
export function Notice({ tone = 'info', icon, children, live = 'status' }: { tone?: 'info' | 'success' | 'warning'; icon?: string; children: ReactNode; live?: 'status' | 'alert' | 'none' }): ReactElement {
  return (
    <div className={`callout ${tone}`} role={live === 'none' ? undefined : live}>
      <Icon name={icon ?? (tone === 'success' ? 'check' : tone === 'warning' ? 'alert' : 'lock')} size={16} />
      <span>{children}</span>
    </div>
  )
}

interface PaginationProps {
  page: number
  pageSize: number
  total: number
  onPage: (page: number) => void
  busy?: boolean
}

export function Pagination({ page, pageSize, total, onPage, busy = false }: PaginationProps): ReactElement {
  const totalPages = Math.max(1, Math.ceil((total || 0) / (pageSize || 1)))
  return (
    <nav className="pagination" aria-label="Pagination">
      <span aria-live="polite">Page {page} of {totalPages} · {total.toLocaleString('en-US')} records</span>
      <div>
        <button type="button" disabled={busy || page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <button type="button" disabled={busy || page >= totalPages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </nav>
  )
}

interface ConfirmDialogProps {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  cancelLabel?: string
  tone?: 'primary' | 'danger'
  busy?: boolean
  confirmDisabled?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Modal built on the native <dialog>: focus is trapped, Escape cancels, the page
 * behind is inert, and focus returns to the opener when it closes. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = 'Cancel',
  tone = 'primary',
  busy = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps): ReactElement {
  const ref = useRef<HTMLDialogElement | null>(null)
  const titleId = useId()
  const opener = useRef<Element | null>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      opener.current = document.activeElement
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
    } else if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
      if (opener.current instanceof HTMLElement) opener.current.focus()
    }
  }, [open])

  return (
    <dialog
      ref={ref}
      className="confirm-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => { event.preventDefault(); if (!busy) onCancel() }}
    >
      <div className="dialog-body">
        <h2 id={titleId}>{title}</h2>
        <div className="dialog-content">{children}</div>
      </div>
      <div className="dialog-actions">
        <button type="button" className="button button-secondary" disabled={busy} onClick={onCancel}>{cancelLabel}</button>
        <button type="button" className={`button button-${tone}`} disabled={busy || confirmDisabled} onClick={onConfirm}>
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </dialog>
  )
}

/** Shows a currency list as separate, labelled chips so no figure can be read as a combined total. */
export function CurrencyChips({ items }: { items: { currency: string; text: string }[] }): ReactElement {
  if (!items.length) return <span className="muted-label">—</span>
  return (
    <ul className="currency-chips">
      {items.map((item) => <li key={item.currency}><span>{item.currency}</span>{item.text}</li>)}
    </ul>
  )
}
