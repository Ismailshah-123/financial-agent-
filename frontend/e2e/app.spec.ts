/**
 * Journeys against a REAL backend. They need E2E_EMAIL and E2E_PASSWORD for a user in a TEST
 * environment. Mutating journeys are opt-in via environment flags and must never target a
 * production company or production finances.
 */
import { expect, test } from '@playwright/test'
import { CREDENTIALS_AVAILABLE, login } from './helpers'

test.skip(!CREDENTIALS_AVAILABLE, 'E2E_EMAIL and E2E_PASSWORD are required for authenticated journeys')

test('journey 1: dashboard to receivables to customer detail by URL', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: /receivables/i }).click()
  await expect(page.getByRole('heading', { name: 'Receivables' })).toBeVisible()
  test.skip(!process.env.E2E_CUSTOMER_ID, 'E2E_CUSTOMER_ID is required for the customer detail journey')
  await page.goto(`/receivables/customers/${process.env.E2E_CUSTOMER_ID}`)
  await expect(page.getByRole('heading', { name: 'Customer intelligence' })).toBeVisible()
})

test('journey 2: payables workspace and vendor detail', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: /payables/i }).click()
  await expect(page.getByRole('heading', { name: 'Payables' })).toBeVisible()
  const firstVendor = page.locator('.link-button').first()
  if (await firstVendor.count()) {
    await firstVendor.click()
    await expect(page.getByRole('heading', { name: 'Vendor profile' })).toBeVisible()
  }
})

test('journey 3: approval inbox lifecycle views', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: /approval inbox/i }).first().click()
  await expect(page.getByRole('heading', { name: 'Approval inbox' })).toBeVisible()
  for (const tab of [/awaiting execution/i, /failed/i, /executed/i, /rejected/i, /pending/i]) {
    await page.getByRole('tab', { name: tab }).click()
    await expect(page.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true')
  }
  test.skip(process.env.E2E_RUN_APPROVAL_MUTATION !== 'true', 'Set E2E_RUN_APPROVAL_MUTATION=true only in a controlled test environment')
  const approve = page.getByRole('button', { name: /approve recommendation/i }).first()
  if (await approve.count()) {
    await approve.click()
    await page.getByRole('button', { name: /record approval/i }).click()
    await expect(page.getByText(/approval recorded/i)).toBeVisible()
  }
})

test('journey 4: agent center shows the backend catalog', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: /ai agents/i }).click()
  await expect(page.getByRole('heading', { name: 'AI Agent Center' })).toBeVisible()
  test.skip(process.env.E2E_RUN_AGENT !== 'true', 'Set E2E_RUN_AGENT=true only in a controlled test environment')
  await page.getByRole('button', { name: /run agent/i }).click()
})

test('journey 5: reports run for a chosen currency', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: /^reports/i }).click()
  await expect(page.getByRole('heading', { name: 'Reports' })).toBeVisible()
  const currency = page.getByLabel('Currency')
  if (await currency.count()) {
    const options = await currency.locator('option').allTextContents()
    const code = options.find((text) => /^[A-Z]{3}$/.test(text.trim()))
    if (code) await currency.selectOption(code.trim())
    await page.getByRole('button', { name: /run report/i }).click()
    await expect(page.getByText(/all amounts are in/i)).toBeVisible()
  }
})

test('journey 6: SAP workspace reports verified state, never an assumed one', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: /sap integration/i }).click()
  await expect(page.getByRole('heading', { name: 'SAP Business One' })).toBeVisible()
  await expect(page.getByText(/no live sap company has been verified/i)).toBeVisible()
  const verify = page.getByRole('button', { name: /verify read only connection/i })
  if (await verify.isEnabled()) {
    await verify.click()
    await expect(page.getByText(/correlation id/i)).toBeVisible()
  }
  test.skip(process.env.E2E_RUN_SAP !== 'true', 'Set E2E_RUN_SAP=true only with an approved SAP test company')
})

test('journey 7: unauthorized role cannot open permissioned workspaces', async ({ page }) => {
  test.skip(!process.env.E2E_VIEWER_EMAIL || !process.env.E2E_VIEWER_PASSWORD, 'E2E_VIEWER_EMAIL and E2E_VIEWER_PASSWORD are required')
  await login(page, process.env.E2E_VIEWER_EMAIL ?? '', process.env.E2E_VIEWER_PASSWORD ?? '')
  await expect(page.getByRole('link', { name: /audit center/i })).toHaveCount(0)
  await page.goto('/audit')
  await expect(page.getByRole('heading', { name: 'Permission required' })).toBeVisible()
})
