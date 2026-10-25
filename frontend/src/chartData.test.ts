import { describe, expect, it } from 'vitest'
import { agingSegments, attentionItems, countShares, pipelineSegments, scaledDecimal, shareOfTotal } from './chartData'

describe('decimal handling without floating point', () => {
  it('parses plain decimals exactly, even very large ones', () => {
    expect(scaledDecimal('1234567890123456789.126')).toBe(1234567890123456789126000n)
    expect(scaledDecimal('-5')).toBe(-5000000n)
    expect(scaledDecimal('abc')).toBeNull()
    expect(scaledDecimal(undefined)).toBeNull()
  })
  it('computes shares from positive amounts only', () => {
    expect(shareOfTotal(['50', '50'])).toEqual([50, 50])
    expect(shareOfTotal(['1', '3'])).toEqual([25, 75])
    expect(shareOfTotal(['100', '-40', 'x'])).toEqual([100, 0, 0])
    expect(shareOfTotal(['0', '0'])).toEqual([0, 0])
    expect(shareOfTotal([])).toEqual([])
  })
})

describe('aging segments', () => {
  const balance = {
    current_amount: '600.00', amount_1_30: '200.00', amount_31_60: '100.00', amount_61_90: '50.00', amount_91_120: '30.00', amount_121_plus: '20.00',
  }
  it('keeps the API amounts verbatim and orders buckets oldest last', () => {
    const segments = agingSegments(balance)
    expect(segments.map((s) => s.label)).toEqual(['Current', '1 to 30 days', '31 to 60 days', '61 to 90 days', '91 to 120 days', '121+ days'])
    expect(segments[0].amount).toBe('600.00')
    expect(segments[5].amount).toBe('20.00')
  })
  it('derives widths from the amounts when the API sends no percentages', () => {
    expect(agingSegments(balance).map((s) => s.percent)).toEqual([60, 20, 10, 5, 3, 2])
  })
  it('prefers the percentages the API reports and clamps them', () => {
    const segments = agingSegments({ ...balance, bucket_percentages: { current: 70.5, '1-30': 250, '31-60': -3 } })
    expect(segments[0].percent).toBe(70.5)
    expect(segments[1].percent).toBe(100)
    expect(segments[2].percent).toBe(0)
    expect(segments[3].percent).toBe(5) // not reported, so derived
  })
  it('is safe for an empty balance', () => {
    expect(agingSegments({}).every((s) => s.percent === 0 && s.amount === '0')).toBe(true)
  })
})

describe('approval pipeline widths', () => {
  it('keeps every non zero count visible and zero counts empty', () => {
    expect(countShares([98, 1, 0, 1])).toEqual([98, 2, 0, 2])
    expect(countShares([0, 0, 0, 0])).toEqual([0, 0, 0, 0])
    expect(countShares([-4, Number.NaN, 3])).toEqual([0, 0, 100])
  })
  it('maps the summary to labelled segments', () => {
    const segments = pipelineSegments({ pending: 4, awaiting_execution: 3, executing: 0, failed: 1 })
    expect(segments.map((s) => s.value)).toEqual([4, 3, 0, 1])
    expect(segments[3].label).toBe('Failed')
  })
})

describe('attention items', () => {
  it('lists only what actually needs a person, most urgent first', () => {
    const items = attentionItems({ failedExecutions: 2, pendingApprovals: 1, awaitingExecution: 0, overdueReceivables: 5, overduePayables: null })
    expect(items.map((i) => i.key)).toEqual(['failed', 'pending', 'ar'])
    expect(items[0].text).toContain('2 approved actions failed')
    expect(items[1].text).toContain('1 recommendation is waiting')
  })
  it('returns nothing when everything is clear or unknown', () => {
    expect(attentionItems({})).toEqual([])
    expect(attentionItems({ failedExecutions: 0, pendingApprovals: null })).toEqual([])
  })
})
