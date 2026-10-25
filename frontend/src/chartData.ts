/**
 * Pure data preparation for the charts. Nothing here changes a financial figure: amounts are
 * passed through exactly as the API returned them, and the only derived numbers are bar widths,
 * which are presentation. Widths are computed with BigInt on the decimal strings so large
 * balances never pass through floating point.
 */

export interface AgingSegment {
  key: string
  label: string
  tone: string
  /** Amount exactly as the API returned it (decimal string). */
  amount: string
  /** Share of the currency's total, 0 to 100, one decimal place. For drawing only. */
  percent: number
}

const BUCKETS: { key: string; pct: string; label: string; tone: string }[] = [
  { key: 'current_amount', pct: 'current', label: 'Current', tone: 'current' },
  { key: 'amount_1_30', pct: '1-30', label: '1 to 30 days', tone: 'd30' },
  { key: 'amount_31_60', pct: '31-60', label: '31 to 60 days', tone: 'd60' },
  { key: 'amount_61_90', pct: '61-90', label: '61 to 90 days', tone: 'd90' },
  { key: 'amount_91_120', pct: '91-120', label: '91 to 120 days', tone: 'd120' },
  { key: 'amount_121_plus', pct: '121+', label: '121+ days', tone: 'd121' },
]

const SCALE = 6

/** Decimal string to an integer scaled by 10^SCALE. Returns null for anything that is not a plain decimal. */
export function scaledDecimal(value: unknown): bigint | null {
  const text = typeof value === 'number' ? String(value) : typeof value === 'string' ? value.trim() : ''
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text)
  if (!match) return null
  const [, sign, whole, fraction = ''] = match
  const digits = `${whole}${fraction.padEnd(SCALE, '0').slice(0, SCALE)}`
  const result = BigInt(digits)
  return sign === '-' ? -result : result
}

/** Percentage shares (one decimal) of each amount against the sum of the positive amounts. */
export function shareOfTotal(amounts: unknown[]): number[] {
  const scaled = amounts.map((amount) => {
    const value = scaledDecimal(amount)
    return value !== null && value > 0n ? value : 0n
  })
  const total = scaled.reduce((sum, value) => sum + value, 0n)
  if (total === 0n) return scaled.map(() => 0)
  return scaled.map((value) => Number((value * 1000n) / total) / 10)
}

export function agingSegments(balance: Record<string, unknown>): AgingSegment[] {
  const given = (balance.bucket_percentages ?? null) as Record<string, unknown> | null
  const computed = shareOfTotal(BUCKETS.map((bucket) => balance[bucket.key]))
  return BUCKETS.map((bucket, index) => {
    const reported = given ? Number(given[bucket.pct]) : Number.NaN
    const percent = Number.isFinite(reported) ? Math.max(0, Math.min(100, reported)) : computed[index]
    const raw = balance[bucket.key]
    return { key: bucket.key, label: bucket.label, tone: bucket.tone, amount: typeof raw === 'string' || typeof raw === 'number' ? String(raw) : '0', percent }
  })
}

export interface PipelineSegment {
  key: string
  label: string
  tone: string
  value: number
}

export function pipelineSegments(summary: { pending: number; awaiting_execution: number; executing: number; failed: number }): PipelineSegment[] {
  return [
    { key: 'pending', label: 'Pending decision', tone: 'blue', value: summary.pending },
    { key: 'awaiting_execution', label: 'Awaiting execution', tone: 'amber', value: summary.awaiting_execution },
    { key: 'executing', label: 'In progress', tone: 'violet', value: summary.executing },
    { key: 'failed', label: 'Failed', tone: 'rose', value: summary.failed },
  ]
}

/** Whole percentage widths for a set of counts. Every non zero count gets at least 2 so it stays visible. */
export function countShares(values: number[]): number[] {
  const clean = values.map((value) => (Number.isFinite(value) && value > 0 ? Math.floor(value) : 0))
  const total = clean.reduce((sum, value) => sum + value, 0)
  if (total === 0) return clean.map(() => 0)
  return clean.map((value) => (value === 0 ? 0 : Math.max(2, Math.round((value * 100) / total))))
}

export interface AttentionItem {
  key: string
  tone: 'rose' | 'amber' | 'blue'
  text: string
  to: 'approvals' | 'receivables' | 'payables'
}

/** Things that need a person, derived only from counts the API returned. */
export function attentionItems(input: {
  failedExecutions?: number | null
  pendingApprovals?: number | null
  awaitingExecution?: number | null
  overdueReceivables?: number | null
  overduePayables?: number | null
}): AttentionItem[] {
  const items: AttentionItem[] = []
  const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`
  if (input.failedExecutions && input.failedExecutions > 0) items.push({ key: 'failed', tone: 'rose', to: 'approvals', text: `${plural(input.failedExecutions, 'approved action failed', 'approved actions failed')} to execute and need review` })
  if (input.pendingApprovals && input.pendingApprovals > 0) items.push({ key: 'pending', tone: 'blue', to: 'approvals', text: `${plural(input.pendingApprovals, 'recommendation is', 'recommendations are')} waiting for a decision` })
  if (input.awaitingExecution && input.awaitingExecution > 0) items.push({ key: 'awaiting', tone: 'amber', to: 'approvals', text: `${plural(input.awaitingExecution, 'approved action is', 'approved actions are')} waiting to be executed` })
  if (input.overdueReceivables && input.overdueReceivables > 0) items.push({ key: 'ar', tone: 'amber', to: 'receivables', text: `${plural(input.overdueReceivables, 'receivable invoice is', 'receivable invoices are')} overdue` })
  if (input.overduePayables && input.overduePayables > 0) items.push({ key: 'ap', tone: 'amber', to: 'payables', text: `${plural(input.overduePayables, 'payment obligation is', 'payment obligations are')} overdue` })
  return items
}
