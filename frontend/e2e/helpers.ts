import { expect, type Page } from '@playwright/test'

export const CREDENTIALS_AVAILABLE = Boolean(process.env.E2E_EMAIL && process.env.E2E_PASSWORD)

/** Signs in through the real login form against a real backend. */
export async function login(page: Page, email = process.env.E2E_EMAIL ?? '', password = process.env.E2E_PASSWORD ?? ''): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Email address').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: /continue to workspace/i }).click()
  await expect(page.locator('#main-content')).toBeVisible()
}

export const ALL_PERMISSIONS = [
  'ar_invoice:read', 'invoice:read', 'approval_request:read', 'approval_request:action', 'payment:approve',
  'agent:invoke', 'agent:configure', 'report:view', 'audit_log:read',
]

export function userFor(permissions: string[], role = 'finance_director') {
  return { id: 'u-1', email: 'tester@example.com', full_name: 'Test User', role, is_active: true, permissions }
}

/** Installs a fake backend. Nothing here talks to a real server, SAP or database. */
export async function mockBackend(page: Page, options: { permissions?: string[]; extra?: (path: string, method: string) => unknown } = {}): Promise<{ calls: string[] }> {
  const calls: string[] = []
  const permissions = options.permissions ?? ALL_PERMISSIONS
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    calls.push(`${request.method()} ${path}`)
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    const custom = options.extra?.(path, request.method())
    if (custom !== undefined) return respond(custom)
    if (path === '/auth/login') return respond({ access_token: 'a', refresh_token: 'r', token_type: 'bearer', expires_in: 1800 })
    if (path === '/auth/me') return respond(userFor(permissions))
    if (path === '/health/ready') return respond({ status: 'ready', service: 'finance-ai' })
    if (path === '/approval-requests/summary') return respond({ pending: 0, awaiting_execution: 0, executing: 0, failed: 0 })
    if (path === '/approval-requests') return respond([])
    if (path === '/aging/summary') return respond({ as_of: '2026-10-14', currency: null, total_outstanding: null, overdue_amount: null, open_invoice_count: 0, overdue_invoice_count: 0, customer_count: 0, oldest_days_overdue: 0, currency_balances: [] })
    if (path === '/aging/customers') return respond({ items: [], total: 0, page: 1, page_size: 25 })
    if (path === '/ap-priority/summary') return respond({ currency: null, total_payable: null, overdue_amount: null, open_obligation_count: 0, overdue_count: 0, currency_balances: [] })
    if (path === '/reports/currencies') return respond({ currencies: ['USD', 'PKR'] })
    return respond({ error_code: 'not_found', message: 'Not mocked' }, 404)
  })
  return { calls }
}

export async function signInMocked(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Email address').fill('tester@example.com')
  await page.getByLabel('Password').fill('a-long-password')
  await page.getByRole('button', { name: /continue to workspace/i }).click()
  await expect(page.locator('#main-content')).toBeVisible()
}
