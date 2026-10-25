/**
 * Pure route table. Every workspace has a real URL (including detail pages), so
 * links can be bookmarked, shared, reloaded and used with the back button.
 * Nothing here touches `window`, which keeps it trivially unit-testable.
 */

export type RouteName =
  | 'dashboard'
  | 'receivables'
  | 'customer'
  | 'payables'
  | 'vendor'
  | 'approvals'
  | 'agents'
  | 'reports'
  | 'sap'
  | 'audit'
  | 'settings'

export interface RouteDefinition {
  name: RouteName
  /** Path pattern; `:id` segments are captured as params. */
  pattern: string
  title: string
  /** Permission the backend requires for the data this workspace shows. */
  permission?: string
  /** Name of the sidebar entry that should be highlighted. */
  navGroup: RouteName
}

export const ROUTES: readonly RouteDefinition[] = [
  { name: 'dashboard', pattern: '/', title: 'Overview', navGroup: 'dashboard' },
  { name: 'receivables', pattern: '/receivables', title: 'Receivables', permission: 'ar_invoice:read', navGroup: 'receivables' },
  { name: 'customer', pattern: '/receivables/customers/:id', title: 'Customer detail', permission: 'ar_invoice:read', navGroup: 'receivables' },
  { name: 'payables', pattern: '/payables', title: 'Payables', permission: 'invoice:read', navGroup: 'payables' },
  { name: 'vendor', pattern: '/payables/vendors/:id', title: 'Vendor detail', permission: 'invoice:read', navGroup: 'payables' },
  { name: 'approvals', pattern: '/approvals', title: 'Approval Inbox', permission: 'approval_request:read', navGroup: 'approvals' },
  { name: 'agents', pattern: '/agents', title: 'AI Agents', permission: 'agent:invoke', navGroup: 'agents' },
  { name: 'reports', pattern: '/reports', title: 'Reports', permission: 'report:view', navGroup: 'reports' },
  { name: 'sap', pattern: '/sap', title: 'SAP Integration', permission: 'agent:invoke', navGroup: 'sap' },
  { name: 'audit', pattern: '/audit', title: 'Audit Center', permission: 'audit_log:read', navGroup: 'audit' },
  { name: 'settings', pattern: '/settings', title: 'Settings', navGroup: 'settings' },
]

export interface MatchedRoute {
  /** `null` when the path matches no workspace (render a 404, not the dashboard). */
  route: RouteDefinition | null
  params: Record<string, string>
  /** Canonical path the URL should be rewritten to (legacy aliases, trailing slash), if different. */
  redirectTo: string | null
}

const ID_PATTERN = /^[0-9a-fA-F-]{8,64}$/

/** Old bookmarks and in-app links used these flat names. */
const LEGACY_REDIRECTS: Record<string, string> = {
  '/customer-detail': '/receivables',
  '/vendor-detail': '/payables',
  '/approval': '/approvals',
  '/dashboard': '/',
}

function normalize(pathname: string): string {
  let path = pathname.split('?')[0].split('#')[0] || '/'
  if (!path.startsWith('/')) path = `/${path}`
  while (path.length > 1 && path.endsWith('/')) path = path.slice(0, -1)
  return path
}

export function matchRoute(pathname: string): MatchedRoute {
  const path = normalize(pathname)
  const legacy = LEGACY_REDIRECTS[path]
  if (legacy) return { route: null, params: {}, redirectTo: legacy }

  const segments = path.split('/').filter(Boolean)
  for (const route of ROUTES) {
    const patternSegments = route.pattern.split('/').filter(Boolean)
    if (patternSegments.length !== segments.length) continue
    const params: Record<string, string> = {}
    let matched = true
    for (let i = 0; i < patternSegments.length; i += 1) {
      const expected = patternSegments[i]
      const actual = segments[i]
      if (expected.startsWith(':')) {
        if (!ID_PATTERN.test(actual)) { matched = false; break }
        params[expected.slice(1)] = actual
      } else if (expected !== actual) {
        matched = false
        break
      }
    }
    if (matched) {
      const rawPath = pathname.split('?')[0].split('#')[0]
      return { route, params, redirectTo: rawPath !== path ? path : null }
    }
  }
  return { route: null, params: {}, redirectTo: null }
}

export function buildPath(name: RouteName, params: Record<string, string> = {}): string {
  const route = ROUTES.find((candidate) => candidate.name === name)
  if (!route) throw new Error(`Unknown route: ${name}`)
  return route.pattern
    .split('/')
    .map((segment) => {
      if (!segment.startsWith(':')) return segment
      const value = params[segment.slice(1)]
      if (!value) throw new Error(`Route ${name} requires param ${segment.slice(1)}`)
      return encodeURIComponent(value)
    })
    .join('/') || '/'
}

export function permissionFor(route: RouteDefinition | null): string | null {
  return route?.permission ?? null
}

/** Sidebar entries, in display order. Detail routes highlight their parent. */
export const NAV_ITEMS: readonly { name: RouteName; label: string; icon: string; permission?: string }[] = [
  { name: 'dashboard', label: 'Overview', icon: 'dashboard' },
  { name: 'receivables', label: 'Receivables', icon: 'users', permission: 'ar_invoice:read' },
  { name: 'payables', label: 'Payables', icon: 'wallet', permission: 'invoice:read' },
  { name: 'approvals', label: 'Approval Inbox', icon: 'inbox', permission: 'approval_request:read' },
  { name: 'agents', label: 'AI Agents', icon: 'bot', permission: 'agent:invoke' },
  { name: 'reports', label: 'Reports', icon: 'chart', permission: 'report:view' },
  { name: 'sap', label: 'SAP Integration', icon: 'plug', permission: 'agent:invoke' },
  { name: 'audit', label: 'Audit Center', icon: 'shield', permission: 'audit_log:read' },
]
