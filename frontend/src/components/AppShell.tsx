import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, checkBackendReadiness } from '../api'
import { useMediaQuery } from '../hooks'
import { NAV_ITEMS, buildPath, type RouteDefinition } from '../router'
import type { ApprovalSummary, User } from '../types'
import { Icon } from './Icons'
import CommandPalette from './CommandPalette'
import Link from './Link'
import { BrandMark } from './ui'

interface AppShellProps {
  user: User
  can: (permission: string) => boolean
  route: RouteDefinition | null
  onSignOut: () => void
  children: ReactNode
}

export default function AppShell({ user, can, route, onSignOut, children }: AppShellProps) {
  const isMobile = useMediaQuery('(max-width: 900px)')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [backendReady, setBackendReady] = useState<boolean | null>(null)
  const [summary, setSummary] = useState<ApprovalSummary | null>(null)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement | null>(null)
  const closeButton = useRef<HTMLButtonElement | null>(null)
  const userMenuTrigger = useRef<HTMLButtonElement | null>(null)
  const canReadApprovals = can('approval_request:read')
  const initials = (user.full_name || user.email || 'F')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()
  const visibleNav = NAV_ITEMS.filter((item) => !item.permission || can(item.permission))
  const activeGroup = route?.navGroup ?? null
  const drawerOpen = isMobile && mobileOpen

  // Close transient UI whenever the page changes or the viewport stops being mobile.
  useEffect(() => { setMobileOpen(false); setUserMenuOpen(false) }, [route?.name])
  useEffect(() => { if (!isMobile) setMobileOpen(false) }, [isMobile])

  useEffect(() => {
    if (drawerOpen) closeButton.current?.focus()
  }, [drawerOpen])

  useEffect(() => {
    if (!drawerOpen && !userMenuOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (userMenuOpen) { setUserMenuOpen(false); userMenuTrigger.current?.focus() }
      else { setMobileOpen(false); menuButton.current?.focus() }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [drawerOpen, userMenuOpen])

  useEffect(() => {
    const controller = new AbortController()
    const refresh = async () => {
      const ready = await checkBackendReadiness(controller.signal)
      if (!controller.signal.aborted) setBackendReady(ready)
    }
    void refresh()
    const timer = window.setInterval(refresh, 30000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [])

  useEffect(() => {
    if (!canReadApprovals) { setSummary(null); return }
    const controller = new AbortController()
    const refresh = async () => {
      try {
        const next = await api.get<ApprovalSummary>('/approval-requests/summary', undefined, controller.signal)
        if (!controller.signal.aborted) setSummary(next)
      } catch {
        // An unknown count is never presented as zero.
        if (!controller.signal.aborted) setSummary(null)
      }
    }
    void refresh()
    const timer = window.setInterval(refresh, 60000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [canReadApprovals])

  const badge = summary ? summary.pending : null
  const attention = summary ? summary.failed + summary.executing : 0
  const approvalLabel = summary
    ? `Open approval inbox, ${summary.pending} pending, ${summary.awaiting_execution} awaiting execution${summary.failed ? `, ${summary.failed} failed` : ''}`
    : 'Open approval inbox'

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside
        className={`sidebar ${drawerOpen ? 'open' : ''}`}
        aria-label="Workspace navigation"
        // Off-screen links must not be reachable by keyboard while the drawer is closed.
        inert={isMobile && !mobileOpen}
      >
        <div className="sidebar-top">
          <BrandMark compact />
          <button ref={closeButton} type="button" className="mobile-close" onClick={() => { setMobileOpen(false); menuButton.current?.focus() }} aria-label="Close navigation">
            <Icon name="x" />
          </button>
        </div>
        <div className="product-lockup">
          <div className="product-dot" aria-hidden="true" />
          <div><strong>Finance AI</strong><span>Control Center</span></div>
        </div>
        <nav className="nav-section" aria-label="Primary">
          <span className="nav-label">Workspace</span>
          {visibleNav.map((item) => (
            <Link
              key={item.name}
              to={buildPath(item.name)}
              className={`nav-item ${activeGroup === item.name ? 'active' : ''}`}
              current={activeGroup === item.name}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
              {item.name === 'approvals' && badge !== null && badge > 0 && <em className="nav-count" aria-hidden="true">{badge >= 100 ? '99+' : badge}</em>}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <Link to={buildPath('settings')} className={`nav-item ${activeGroup === 'settings' ? 'active' : ''}`} current={activeGroup === 'settings'}>
            <Icon name="settings" /><span>Settings</span>
          </Link>
          <div className="sidebar-user">
            <span className="avatar" aria-hidden="true">{initials}</span>
            <div><strong>{user.full_name || 'Finance user'}</strong><span>{user.role.replaceAll('_', ' ')}</span></div>
            <button type="button" onClick={onSignOut} aria-label="Sign out"><Icon name="logout" size={15} /></button>
          </div>
        </div>
      </aside>
      {drawerOpen && <button type="button" className="backdrop" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
      <div className="main-area" inert={drawerOpen}>
        <header className="topbar">
          <div className="topbar-left">
            <button ref={menuButton} type="button" className="mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation" aria-expanded={drawerOpen}><Icon name="menu" /></button>
            <nav className="breadcrumb" aria-label="Breadcrumb">
              <Link to="/" className="breadcrumb-root">Finance</Link>
              <Icon name="chevron" size={14} />
              <strong aria-current="page">{route?.title ?? 'Not found'}</strong>
            </nav>
            <CommandPalette can={can} />
          </div>
          <div className="topbar-right">
            <span className={`live-status ${backendReady === false ? 'down' : ''}`} role="status" aria-live="polite">
              <i aria-hidden="true" /> {backendReady === null ? 'Checking backend' : backendReady ? 'Backend ready' : 'Backend unavailable'}
            </span>
            <div className="topbar-divider" />
            {canReadApprovals && (
              <Link to={buildPath('approvals')} className="header-approval-button" aria-label={approvalLabel} title="Open approval inbox">
                <Icon name="inbox" size={17} />
                <span>Approvals</span>
                {badge !== null && badge > 0 && <em>{badge >= 100 ? '99+' : badge}</em>}
                {attention > 0 && <b className="attention-dot" title={`${attention} need reconciliation`} />}
              </Link>
            )}
            <div className="topbar-user-wrap">
              <button ref={userMenuTrigger} type="button" className="topbar-avatar user-menu-trigger" onClick={() => setUserMenuOpen((open) => !open)} aria-label="Open user menu" aria-expanded={userMenuOpen}>
                {initials}
              </button>
              {userMenuOpen && (
                <div className="user-menu-popover" aria-label="User menu">
                  <div className="user-menu-identity"><strong>{user.full_name || 'Finance user'}</strong><span>{user.email}</span><small>{user.role.replaceAll('_', ' ')}</small></div>
                  <Link to={buildPath('settings')} className="menu-link"><Icon name="settings" size={15} /> Settings</Link>
                  <button type="button" onClick={onSignOut}><Icon name="logout" size={15} /> Sign out</button>
                </div>
              )}
            </div>
          </div>
        </header>
        {children}
      </div>
    </div>
  )
}
