import { NAV_ITEMS, buildPath } from './router'

export interface Command {
  id: string
  label: string
  hint: string
  path: string
  icon: string
}

const HINTS: Record<string, string> = {
  dashboard: 'Exposure, approvals and what needs attention',
  receivables: 'Open invoices, aging and collection priorities',
  payables: 'Payment obligations and vendor exposure',
  approvals: 'Review, approve and execute recommendations',
  agents: 'Run the backend AI agents',
  reports: 'Trial balance, profit and loss, balance sheet',
  sap: 'Service Layer connection and master data sync',
  audit: 'Append only activity trail and chain verification',
}

/** Workspaces the signed in user may open. The server still enforces every permission. */
export function buildNavigationCommands(can: (permission: string) => boolean): Command[] {
  const commands: Command[] = NAV_ITEMS.filter((item) => !item.permission || can(item.permission)).map((item) => ({
    id: `nav:${item.name}`,
    label: item.label,
    hint: HINTS[item.name] ?? '',
    path: buildPath(item.name),
    icon: item.icon,
  }))
  commands.push({ id: 'nav:settings', label: 'Settings', hint: 'Your profile, permissions and service status', path: buildPath('settings'), icon: 'settings' })
  return commands
}

/** Case insensitive match; label prefix beats word prefix beats substring beats hint text. */
export function filterCommands(commands: Command[], query: string): Command[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return commands
  const scored: { command: Command; score: number; index: number }[] = []
  commands.forEach((command, index) => {
    const label = command.label.toLowerCase()
    let score = -1
    if (label.startsWith(needle)) score = 4
    else if (label.split(/\s+/).some((word) => word.startsWith(needle))) score = 3
    else if (label.includes(needle)) score = 2
    else if (command.hint.toLowerCase().includes(needle)) score = 1
    if (score > 0) scored.push({ command, score, index })
  })
  return scored.sort((a, b) => b.score - a.score || a.index - b.index).map((entry) => entry.command)
}
