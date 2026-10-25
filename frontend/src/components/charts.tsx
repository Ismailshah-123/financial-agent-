import type { ReactElement } from 'react'
import { agingSegments, countShares, type PipelineSegment } from '../chartData'
import { formatMoneyAmount } from '../formatters'

/** One stacked bar per currency. Colour is never the only signal: every segment is also named,
 * valued and given a percentage in the legend, and the bar has a text equivalent. */
export function AgingBar({ balance, currency }: { balance: Record<string, unknown>; currency: string }): ReactElement {
  const segments = agingSegments(balance)
  const visible = segments.filter((segment) => segment.percent > 0)
  const summary = visible.length ? visible.map((segment) => `${segment.label} ${segment.percent.toFixed(1)} percent`).join(', ') : 'no open balance'
  const total = balance.total_outstanding
  return (
    <figure className="chart-block">
      <figcaption>
        <span className="chart-currency">{currency}</span>
        {typeof total === 'string' && <strong>{formatMoneyAmount(total, currency)} outstanding</strong>}
      </figcaption>
      <div className="stack-bar" role="img" aria-label={`${currency} aging: ${summary}`}>
        {visible.map((segment) => (
          <span key={segment.key} className={`seg seg-${segment.tone}`} style={{ width: `${segment.percent}%` }} title={`${segment.label}: ${formatMoneyAmount(segment.amount, currency)}`} />
        ))}
      </div>
      <ul className="legend">
        {segments.map((segment) => (
          <li key={segment.key}>
            <i className={`dot seg-${segment.tone}`} aria-hidden="true" />
            <span>{segment.label}</span>
            <strong>{formatMoneyAmount(segment.amount, currency)}</strong>
            <em>{segment.percent.toFixed(1)}%</em>
          </li>
        ))}
      </ul>
    </figure>
  )
}

/** Counts (not money) as a single segmented bar with a legend. */
export function PipelineBar({ segments, label }: { segments: PipelineSegment[]; label: string }): ReactElement {
  const widths = countShares(segments.map((segment) => segment.value))
  const total = segments.reduce((sum, segment) => sum + segment.value, 0)
  const summary = total === 0 ? 'nothing in the pipeline' : segments.filter((s) => s.value > 0).map((s) => `${s.label} ${s.value}`).join(', ')
  return (
    <figure className="chart-block">
      <div className="stack-bar" role="img" aria-label={`${label}: ${summary}`}>
        {segments.map((segment, index) => (widths[index] > 0 ? <span key={segment.key} className={`seg seg-tone-${segment.tone}`} style={{ width: `${widths[index]}%` }} /> : null))}
      </div>
      <ul className="legend legend-tight">
        {segments.map((segment) => (
          <li key={segment.key}>
            <i className={`dot seg-tone-${segment.tone}`} aria-hidden="true" />
            <span>{segment.label}</span>
            <strong>{segment.value}</strong>
          </li>
        ))}
      </ul>
    </figure>
  )
}
