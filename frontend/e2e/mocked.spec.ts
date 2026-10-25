/**
 * Browser journeys that run against a FAKE backend (page.route), so they need no credentials,
 * database or SAP company and can run in every CI build. They cover the behaviours that matter
 * most for safety: permissions, deep links, session expiry and duplicate-submission protection.
 */
import { expect, test } from '@playwright/test'
import { ALL_PERMISSIONS, mockBackend, signInMocked, userFor } from './helpers'

test('unknown addresses show a not-found page instead of the dashboard', async ({ page }) => {
  await mockBackend(page)
  await signInMocked(page)
  await page.goto('/definitely-not-a-page')
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible()
})

test('a role without audit access sees no Audit link and is refused on the direct URL', async ({ page }) => {
  await mockBackend(page, { permissions: ['approval_request:read', 'report:view'] })
  await signInMocked(page)
  await expect(page.getByRole('link', { name: /audit center/i })).toHaveCount(0)
  await page.goto('/audit')
  await expect(page.getByRole('heading', { name: 'Permission required' })).toBeVisible()
})

test('a customer detail URL survives a reload (deep link)', async ({ page }) => {
  await mockBackend(page, { extra: (path) => (path.startsWith('/aging/customers/') ? { customer_id: 'x' } : undefined) })
  await signInMocked(page)
  await page.goto('/receivables/customers/3f2b8c1e-5d4a-4b7e-9a10-0c2d3e4f5a6b')
  await page.reload()
  await expect(page).toHaveURL(/\/receivables\/customers\/3f2b8c1e/)
  await expect(page.getByRole('heading', { name: 'Page not found' })).toHaveCount(0)
})

test('a refused refresh token ends the session with an explanation', async ({ page }) => {
  await mockBackend(page)
  await signInMocked(page)
  await page.route('**/api/v1/aging/summary', (route) => route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ message: 'expired' }) }))
  await page.route('**/api/v1/auth/refresh', (route) => route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ message: 'revoked' }) }))
  await page.getByRole('link', { name: /receivables/i }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByText(/session expired/i)).toBeVisible()
})

test('executing an approved payment is sent once even when the confirm button is clicked twice', async ({ page }) => {
  const item = {
    id: '11111111-1111-4111-8111-111111111111', decision_id: 'd', agent_type: 'accounts_payable', correlation_id: 'c', actor_id: 'a',
    risk_level: 'medium', summary: 'Pay vendor invoice INV-1', status: 'approved', resolved_at: null, resolved_by_id: null, resolution_notes: null,
    action_type: 'payment_execute', action_payload: {}, idempotency_key: null, execution_status: 'execution_pending',
    execution_attempted_at: null, executed_at: null, execution_result: null, execution_error: null, created_at: '2026-10-14T08:00:00Z',
    decision: { reasoning: 'Due in 2 days.', financial_impact: { amount: '1500.00', currency: 'USD' }, supporting_evidence: [], relevant_policies: [] },
  }
  let executeCalls = 0
  let sawIdempotencyKey = ''
  await mockBackend(page, { extra: (path, method) => {
    if (path === '/approval-requests' && method === 'GET') return [item]
    if (path === '/approval-requests/summary') return { pending: 0, awaiting_execution: 1, executing: 0, failed: 0 }
    return undefined
  } })
  await page.route('**/api/v1/approval-requests/*/execute', async (route) => {
    executeCalls += 1
    sawIdempotencyKey = route.request().headers()['idempotency-key'] ?? ''
    await new Promise((resolve) => setTimeout(resolve, 400))
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...item, execution_status: 'executed', executed_at: '2026-10-14T09:00:00Z' }) })
  })
  await signInMocked(page)
  await page.getByRole('link', { name: /approval inbox/i }).first().click()
  await page.getByRole('tab', { name: /awaiting execution/i }).click()
  await page.getByRole('button', { name: /execute approved action/i }).click()
  const confirm = page.getByRole('button', { name: 'Execute action' })
  await expect(confirm).toBeVisible()
  await confirm.dblclick()
  await expect(page.getByText(/execution completed/i)).toBeVisible()
  expect(executeCalls).toBe(1)
  expect(sawIdempotencyKey).toContain('approval:')
})

test('the dialog traps focus and closes with Escape', async ({ page }) => {
  const pending = {
    id: '22222222-2222-4222-8222-222222222222', decision_id: 'd', agent_type: 'collections', correlation_id: 'c', actor_id: 'a', risk_level: 'low',
    summary: 'Send reminder to Acme', status: 'pending', resolved_at: null, resolved_by_id: null, resolution_notes: null, action_type: null,
    action_payload: {}, idempotency_key: null, execution_status: 'not_applicable', execution_attempted_at: null, executed_at: null,
    execution_result: null, execution_error: null, created_at: '2026-10-14T08:00:00Z', decision: { reasoning: 'Overdue.' },
  }
  await mockBackend(page, { extra: (path, method) => (path === '/approval-requests' && method === 'GET' ? [pending] : undefined) })
  await signInMocked(page)
  await page.getByRole('link', { name: /approval inbox/i }).first().click()
  const opener = page.getByRole('button', { name: /reject/i }).first()
  await opener.click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeHidden()
  await expect(opener).toBeFocused()
})

test('reports require choosing a currency when the ledger holds several', async ({ page }) => {
  await mockBackend(page)
  await signInMocked(page)
  await page.getByRole('link', { name: /^reports/i }).click()
  await expect(page.getByRole('button', { name: /run report/i })).toBeDisabled()
  await page.getByLabel('Currency').selectOption('USD')
  await expect(page.getByRole('button', { name: /run report/i })).toBeEnabled()
})

test('the mobile drawer opens and Escape returns focus to the menu button', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 })
  await mockBackend(page, { permissions: ALL_PERMISSIONS })
  await signInMocked(page)
  await expect(page.getByRole('button', { name: 'Open navigation' })).toBeVisible()
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Open navigation' })).toBeFocused()
})

test('identity comes from the server, not from the cached browser copy', async ({ page }) => {
  await mockBackend(page)
  await signInMocked(page)
  await page.evaluate(() => sessionStorage.setItem('finance_user', JSON.stringify({ id: 'x', email: 'evil@example.com', full_name: 'Evil Admin', role: 'admin', is_active: true, permissions: ['*'] })))
  await page.reload()
  await expect(page.getByText('Evil Admin')).toHaveCount(0)
  await expect(page.getByText(userFor([]).full_name).first()).toBeVisible()
})
