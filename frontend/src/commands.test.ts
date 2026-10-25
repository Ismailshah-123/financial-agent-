import { describe, expect, it } from 'vitest'
import { buildNavigationCommands, filterCommands } from './commands'

describe('navigation commands', () => {
  it('only offers workspaces the user is permitted to open', () => {
    const labels = buildNavigationCommands((permission) => permission === 'report:view').map((c) => c.label)
    expect(labels).toEqual(['Overview', 'Reports', 'Settings'])
  })
  it('offers everything to a fully permitted user and always links to real routes', () => {
    const commands = buildNavigationCommands(() => true)
    expect(commands.length).toBe(9)
    expect(commands.every((c) => c.path.startsWith('/'))).toBe(true)
  })
})

describe('command filtering', () => {
  const commands = buildNavigationCommands(() => true)
  it('returns everything for an empty query', () => {
    expect(filterCommands(commands, '  ')).toHaveLength(commands.length)
  })
  it('ranks label prefixes first', () => {
    expect(filterCommands(commands, 'pay')[0].label).toBe('Payables')
    expect(filterCommands(commands, 'REC')[0].label).toBe('Receivables')
  })
  it('matches later words and hint text', () => {
    expect(filterCommands(commands, 'inbox')[0].label).toBe('Approval Inbox')
    expect(filterCommands(commands, 'balance sheet')[0].label).toBe('Reports')
  })
  it('returns nothing when nothing matches', () => {
    expect(filterCommands(commands, 'zzzz')).toEqual([])
  })
})
