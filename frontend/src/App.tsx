import { Suspense, lazy, useEffect, useMemo, useRef, type ReactElement } from 'react'
import AppShell from './components/AppShell'
import ErrorBoundary from './components/ErrorBoundary'
import Link from './components/Link'
import { LoadingPanel } from './components/ui'
import { useAuth } from './auth'
import { useDocumentTitle } from './hooks'
import { navigate, useLocation } from './navigation'
import { buildPath, matchRoute } from './router'
import Login from './pages/Login'

// Workspaces load on demand so the sign-in screen and shell stay small.
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Receivables = lazy(() => import('./pages/Receivables'))
const CustomerDetail = lazy(() => import('./pages/CustomerDetail'))
const Payables = lazy(() => import('./pages/Payables'))
const VendorDetail = lazy(() => import('./pages/VendorDetail'))
const Approvals = lazy(() => import('./pages/Approvals'))
const Agents = lazy(() => import('./pages/Agents'))
const Reports = lazy(() => import('./pages/Reports'))
const SapIntegration = lazy(() => import('./pages/SapIntegration'))
const Audit = lazy(() => import('./pages/Audit'))
const Settings = lazy(() => import('./pages/Settings'))

function Message({ title, children }: { title: string; children: string }): ReactElement {
  return (
    <div className="empty-state">
      <div className="empty-icon" aria-hidden="true">!</div>
      <div>
        <h1 className="empty-title">{title}</h1>
        <p>{children}</p>
      </div>
    </div>
  )
}

export default function App(): ReactElement {
  const { user, loading, notice, signIn, signOut, can } = useAuth()
  const location = useLocation()
  const match = useMemo(() => matchRoute(location.pathname), [location.pathname])
  const main = useRef<HTMLElement | null>(null)
  const firstRender = useRef(true)

  useDocumentTitle(match.route?.title ?? 'Page not found')

  // Canonicalise legacy and malformed URLs without adding a history entry.
  useEffect(() => {
    if (match.redirectTo) navigate(`${match.redirectTo}${location.search}`, { replace: true })
  }, [match.redirectTo])

  // Move focus to the new page so keyboard and screen-reader users land at its start.
  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return }
    main.current?.focus({ preventScroll: false })
  }, [match.route?.name, match.params.id])

  const page = useMemo((): ReactElement => {
    const { route, params } = match
    if (!route) {
      return (
        <Message title="Page not found">
          This address does not match a finance workspace. Use the navigation to continue.
        </Message>
      )
    }
    if (route.permission && !can(route.permission)) {
      return <Message title="Permission required">Your current role does not have access to this workspace.</Message>
    }
    switch (route.name) {
      case 'receivables': return <Receivables onCustomer={(id: string) => navigate(buildPath('customer', { id }))} />
      case 'customer': return <CustomerDetail id={params.id} onBack={() => navigate(buildPath('receivables'))} can={can} />
      case 'payables': return <Payables onVendor={(id: string) => navigate(buildPath('vendor', { id }))} />
      case 'vendor': return <VendorDetail id={params.id} onBack={() => navigate(buildPath('payables'))} can={can} />
      case 'approvals': return <Approvals can={can} />
      case 'agents': return <Agents />
      case 'reports': return <Reports />
      case 'sap': return <SapIntegration can={can} />
      case 'audit': return <Audit />
      case 'settings': return user ? <Settings user={user} onSignOut={() => signOut('user')} can={can} /> : <></>
      default: return <Dashboard can={can} user={user} />
    }
  }, [match, can, user, signOut])

  if (loading) {
    return <div className="boot-screen" role="status"><div className="boot-mark" aria-hidden="true">V</div><span>Loading Finance AI…</span></div>
  }
  if (!user) return <Login onLogin={signIn} notice={notice} />

  return (
    <AppShell user={user} can={can} route={match.route} onSignOut={() => signOut('user')}>
      <main id="main-content" ref={main} tabIndex={-1} className="content-area">
        {/* Keyed by route so a crash in one workspace resets when the user navigates away. */}
        <ErrorBoundary key={`${match.route?.name ?? 'none'}:${match.params.id ?? ''}`}>
          <Suspense fallback={<LoadingPanel label="Loading workspace…" />}>{page}</Suspense>
        </ErrorBoundary>
        {!match.route && <p className="not-found-link"><Link to="/" className="text-button">Go to overview</Link></p>}
      </main>
    </AppShell>
  )
}
