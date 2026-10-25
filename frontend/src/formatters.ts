const MISSING = '—'
const ZERO_DECIMAL_CURRENCIES = new Set(['JPY', 'KRW', 'CLP', 'VND'])
const THREE_DECIMAL_CURRENCIES = new Set(['BHD', 'KWD', 'OMR', 'JOD', 'TND'])

function decimalParts(value: unknown): { negative: boolean; integer: string; fraction: string } | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'bigint') return null
  const raw = String(value).trim()
  if (!/^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(raw)) return null
  const negative = raw.startsWith('-')
  const unsigned = raw.replace(/^[+-]/, '')
  const [integerPart = '0', fractionPart = ''] = unsigned.split('.')
  return { negative, integer: (integerPart || '0').replace(/^0+(?=\d)/, ''), fraction: fractionPart }
}

function roundDecimal(parts: { negative: boolean; integer: string; fraction: string }, digits: number): string {
  const kept = parts.fraction.padEnd(digits + 1, '0')
  let integer = parts.integer
  let fraction = kept.slice(0, digits)
  if (kept.charAt(digits) >= '5') {
    const combined = BigInt(`${integer}${fraction}` || '0') + 1n
    const raw = combined.toString().padStart(digits + 1, '0')
    integer = digits ? raw.slice(0, -digits) : raw
    fraction = digits ? raw.slice(-digits) : ''
  }
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const sign = parts.negative && (BigInt(integer) !== 0n || BigInt(fraction || '0') !== 0n) ? '-' : ''
  return `${sign}${grouped}${digits ? `.${fraction.padEnd(digits, '0')}` : ''}`
}

/** Digits only (no currency code), rounded half-up on the decimal string itself. */
export function formatMoneyAmount(value: unknown, currency: string): string {
  const parts = decimalParts(value)
  if (!parts) return MISSING
  const code = String(currency || '').toUpperCase()
  const digits = ZERO_DECIMAL_CURRENCIES.has(code) ? 0 : THREE_DECIMAL_CURRENCIES.has(code) ? 3 : 2
  return roundDecimal(parts, digits)
}

/** `currency` defaults to PKR only for legacy call sites. Prefer passing the
 * currency the backend returned; never infer one for an amount that lacks it. */
export function formatMoney(value: unknown, currency = 'PKR'): string {
  const amount = formatMoneyAmount(value, String(currency || 'PKR'))
  if (amount === MISSING) return MISSING
  return `${String(currency || 'PKR').toUpperCase()} ${amount}`
}

export function formatDate(value: unknown): string {
  if (value === null || value === undefined || value === '') return MISSING
  const raw = String(value)
  // Date-only API values are calendar dates, not UTC instants. Parse them in
  // local time so western timezones do not display the previous day.
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(raw)
  const date = new Date(dateOnly ? `${raw}T00:00:00` : raw)
  if (Number.isNaN(date.getTime())) return MISSING
  return date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

export function formatPercent(value: unknown, digits = 1): string {
  const amount = typeof value === 'number' ? value : value === null || value === undefined || value === '' ? Number.NaN : Number(value)
  if (!Number.isFinite(amount)) return MISSING
  return `${amount.toFixed(digits)}%`
}

export function formatNumber(value: unknown, digits = 0): string {
  const amount = typeof value === 'number' ? value : value === null || value === undefined || value === '' ? Number.NaN : Number(value)
  if (!Number.isFinite(amount)) return MISSING
  return amount.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function formatLabel(value: unknown): string {
  return String(value || MISSING).replaceAll('_', ' ')
}

export function localDateInputValue(date = new Date()): string {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}


/** Displays server-supplied per-currency amounts without combining currencies. */
export function formatCurrencyAmounts(currencyBalances: unknown, valueKey: string, fallbackAmount?: unknown, fallbackCurrency?: unknown): string {
  if (Array.isArray(currencyBalances) && currencyBalances.length > 0) {
    return currencyBalances.map((value: unknown) => {
      if (!value || typeof value !== 'object') return MISSING
      const balance = value as Record<string, unknown>
      if (typeof balance.currency !== 'string' || !balance.currency.trim()) return MISSING
      return formatMoney(balance[valueKey], balance.currency)
    }).join(' · ')
  }
  if (typeof fallbackCurrency !== 'string' || !fallbackCurrency.trim()) return MISSING
  return formatMoney(fallbackAmount, fallbackCurrency)
}

export interface CurrencyAmountItem {
  currency: string
  text: string
}

/** One entry per currency from a server `currency_balances` array. Entries without a
 * currency code are dropped rather than shown under a guessed one. */
export function currencyAmountItems(currencyBalances: unknown, valueKey: string): CurrencyAmountItem[] {
  if (!Array.isArray(currencyBalances)) return []
  const items: CurrencyAmountItem[] = []
  for (const entry of currencyBalances) {
    if (!entry || typeof entry !== 'object') continue
    const balance = entry as Record<string, unknown>
    if (typeof balance.currency !== 'string' || !balance.currency.trim()) continue
    items.push({ currency: balance.currency.toUpperCase(), text: formatMoneyAmount(balance[valueKey], balance.currency) })
  }
  return items
}

/** Date and time for audit/diagnostic displays; never drops the time-of-day. */
export function formatDateTime(value: unknown): string {
  if (value === null || value === undefined || value === '') return MISSING
  const date = new Date(String(value))
  if (Number.isNaN(date.getTime())) return MISSING
  return date.toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
