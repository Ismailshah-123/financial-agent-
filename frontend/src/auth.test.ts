import { describe, expect, it } from 'vitest'
import { hasPermission } from './auth'

describe('permission helper', () => {
  it('authorizes only permissions confirmed on the current server user', () => {
    const user = { id: '1', email: 'a@b.com', full_name: 'A', role: 'viewer', is_active: true, permissions: ['report:view'] }
    expect(hasPermission(user, 'report:view')).toBe(true)
    expect(hasPermission(user, 'payment:approve')).toBe(false)
    expect(hasPermission(null, 'report:view')).toBe(false)
  })
})
