import { describe, expect, it } from 'vitest'
import { NAV_ITEMS, ROUTES, buildPath, matchRoute } from './router'

const ID = '3f2b8c1e-5d4a-4b7e-9a10-0c2d3e4f5a6b'

describe('route matching', () => {
  it('matches list pages and the root', () => {
    expect(matchRoute('/').route?.name).toBe('dashboard')
    expect(matchRoute('/receivables').route?.name).toBe('receivables')
    expect(matchRoute('/approvals').route?.name).toBe('approvals')
  })
  it('captures ids for detail pages so they can be bookmarked and reloaded', () => {
    const customer = matchRoute(`/receivables/customers/${ID}`)
    expect(customer.route?.name).toBe('customer')
    expect(customer.params.id).toBe(ID)
    expect(matchRoute(`/payables/vendors/${ID}`).route?.name).toBe('vendor')
  })
  it('does not silently fall back to the dashboard for unknown paths', () => {
    expect(matchRoute('/no-such-page').route).toBeNull()
    expect(matchRoute('/receivables/customers').route).toBeNull()
    expect(matchRoute('/receivables/customers/../../etc').route).toBeNull()
    expect(matchRoute('/receivables/customers/<script>').route).toBeNull()
  })
  it('redirects legacy flat URLs and trailing slashes', () => {
    expect(matchRoute('/customer-detail').redirectTo).toBe('/receivables')
    expect(matchRoute('/vendor-detail').redirectTo).toBe('/payables')
    expect(matchRoute('/approval').redirectTo).toBe('/approvals')
    expect(matchRoute('/reports/').route?.name).toBe('reports')
    expect(matchRoute('/reports/').redirectTo).toBe('/reports')
  })
  it('ignores query strings and fragments when matching', () => {
    expect(matchRoute('/approvals?view=failed#top').route?.name).toBe('approvals')
  })
})

describe('building paths', () => {
  it('round-trips with the matcher', () => {
    const path = buildPath('customer', { id: ID })
    expect(path).toBe(`/receivables/customers/${ID}`)
    expect(matchRoute(path).params.id).toBe(ID)
    expect(buildPath('dashboard')).toBe('/')
  })
  it('refuses to build a detail path without its id', () => {
    expect(() => buildPath('vendor')).toThrow(/requires param id/)
  })
})

describe('route table integrity', () => {
  it('has unique names and patterns', () => {
    expect(new Set(ROUTES.map((r) => r.name)).size).toBe(ROUTES.length)
    expect(new Set(ROUTES.map((r) => r.pattern)).size).toBe(ROUTES.length)
  })
  it('gives every sidebar entry a real route with the same permission', () => {
    for (const item of NAV_ITEMS) {
      const route = ROUTES.find((r) => r.name === item.name)
      expect(route).toBeDefined()
      expect(route?.permission).toBe(item.permission)
    }
  })
  it('makes detail pages require the same permission as their list', () => {
    expect(ROUTES.find((r) => r.name === 'customer')?.permission).toBe(ROUTES.find((r) => r.name === 'receivables')?.permission)
    expect(ROUTES.find((r) => r.name === 'vendor')?.permission).toBe(ROUTES.find((r) => r.name === 'payables')?.permission)
  })
})
