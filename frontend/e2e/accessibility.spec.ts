import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { ALL_PERMISSIONS, CREDENTIALS_AVAILABLE, login, mockBackend, signInMocked } from './helpers'

// Entrance animations briefly lower opacity, which can produce false colour contrast results.
test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
})

const ROUTES = ['/', '/receivables', '/payables', '/approvals', '/agents', '/reports', '/sap', '/audit', '/settings']

async function audit(page: Page, label: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  const serious = results.violations.filter((item) => item.impact === 'serious' || item.impact === 'critical')
  expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`), `${label} accessibility violations`).toEqual([])
}

test('sign in screen has no serious or critical axe violations', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await audit(page, 'login')
})

// Runs with the fake backend, so it works in every CI build and covers empty states and dialogs.
test('workspaces (mocked data) have no serious or critical axe violations at desktop and mobile widths', async ({ page }) => {
  await mockBackend(page, { permissions: ALL_PERMISSIONS })
  for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 800 }]) {
    await page.setViewportSize(viewport)
    await page.goto('/')
    if (await page.getByLabel('Email address').count()) await signInMocked(page)
    for (const route of ROUTES) {
      await page.goto(route)
      await page.waitForLoadState('networkidle')
      await audit(page, `${route} @ ${viewport.width}px`)
    }
  }
})

test('real backend workspaces have no serious or critical axe violations', async ({ page }) => {
  test.skip(!CREDENTIALS_AVAILABLE, 'E2E_EMAIL and E2E_PASSWORD are required')
  await login(page)
  for (const route of ROUTES) {
    await page.goto(route)
    await page.waitForLoadState('networkidle')
    await audit(page, route)
  }
})

test('pages do not scroll sideways at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 })
  await mockBackend(page, { permissions: ALL_PERMISSIONS })
  await page.goto('/')
  await signInMocked(page)
  for (const route of ROUTES) {
    await page.goto(route)
    await page.waitForLoadState('networkidle')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, `${route} horizontal overflow`).toBeLessThanOrEqual(1)
  }
})
