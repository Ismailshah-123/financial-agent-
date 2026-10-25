import { describe, expect, it } from 'vitest'
import { currencyAmountItems, formatCurrencyAmounts, formatDate, formatDateTime, formatLabel, formatMoney, formatMoneyAmount, formatNumber, formatPercent } from './formatters'

describe('financial formatters', () => {
  it('formats finite money without changing source semantics', () => {
    expect(formatMoney('1234.5', 'PKR')).toBe('PKR 1,234.50')
    expect(formatMoney('999999999999999999.995', 'PKR')).toBe('PKR 1,000,000,000,000,000,000.00')
    expect(formatMoney('-12.5', 'USD')).toBe('USD -12.50')
    expect(formatMoney(null, 'PKR')).toBe('—')
    expect(formatMoney('bad', 'PKR')).toBe('—')
  })
  it('formats currency breakdowns without inventing consolidated totals', () => {
    expect(formatCurrencyAmounts([{currency:'EUR',total_outstanding:'20.20'},{currency:'USD',total_outstanding:'10.10'}], 'total_outstanding')).toBe('EUR 20.20 · USD 10.10')
    expect(formatCurrencyAmounts([], 'total_outstanding', null, null)).toBe('—')
    expect(formatCurrencyAmounts([], 'total_outstanding', '10.00', 'PKR')).toBe('PKR 10.00')
  })
  it('formats percentages and labels consistently', () => {
    expect(formatPercent(12.345, 1)).toBe('12.3%')
    expect(formatLabel('payment_approved')).toBe('payment approved')
  })
  it('formats dates and numbers safely', () => {
    expect(formatDate('not-a-date')).toBe('—')
    expect(formatNumber(1200)).toBe('1,200')
    expect(formatNumber(undefined)).toBe('—')
  })
  it('formats digits without a currency code and keeps decimal precision', () => {
    expect(formatMoneyAmount('1234567890123456789.126', 'USD')).toBe('1,234,567,890,123,456,789.13')
    expect(formatMoneyAmount('1000', 'JPY')).toBe('1,000')
    expect(formatMoneyAmount('1.2345', 'KWD')).toBe('1.235')
    expect(formatMoneyAmount(undefined, 'USD')).toBe('—')
  })
  it('lists one entry per currency and never guesses a missing currency', () => {
    const items = currencyAmountItems([
      { currency: 'usd', total_outstanding: '10.10' },
      { currency: 'PKR', total_outstanding: '2000' },
      { total_outstanding: '5.00' },
      { currency: '  ', total_outstanding: '7.00' },
      null,
    ], 'total_outstanding')
    expect(items).toEqual([{ currency: 'USD', text: '10.10' }, { currency: 'PKR', text: '2,000.00' }])
    expect(currencyAmountItems(undefined, 'total_outstanding')).toEqual([])
  })
  it('keeps the time of day for audit displays', () => {
    expect(formatDateTime('2026-10-13T08:15:30Z')).toMatch(/2026/)
    expect(formatDateTime('nope')).toBe('—')
    expect(formatDateTime(null)).toBe('—')
  })
})
