import type { ReactElement } from 'react'
import { api, API_BASE_URL, checkBackendReadiness } from '../api'
import { idleTimeoutMinutes } from '../auth'
import { Icon } from '../components/Icons'
import { Card, Notice, PageHeader, SectionHeading, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks'
import type { SapStatus, User } from '../types'

interface SettingsProps {
  user: User
  onSignOut: () => void
  can: (permission: string) => boolean
}

function groupPermissions(permissions: string[]): [string, string[]][] {
  const groups = new Map<string, string[]>()
  for (const permission of [...permissions].sort()) {
    const [domain] = permission.split(':')
    groups.set(domain, [...(groups.get(domain) ?? []), permission.slice(domain.length + 1)])
  }
  return [...groups.entries()]
}

export default function Settings({ user, onSignOut, can }: SettingsProps): ReactElement {
  const ready = useAsync((signal) => checkBackendReadiness(signal), [])
  const canSap = can('agent:invoke')
  const sap = useAsync((signal) => (canSap ? api.get<SapStatus>('/sap/status', undefined, signal) : Promise.resolve(null)), [canSap])
  const idle = idleTimeoutMinutes()

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Workspace configuration" title="Settings" description="Your session, your permissions and the live state of the services behind this workspace." />
      <div className="dashboard-grid">
        <Card>
          <SectionHeading title="Your profile" />
          <div className="profile-grid">
            <div><span>Full name</span><strong>{user.full_name || '—'}</strong></div>
            <div><span>Email</span><strong>{user.email}</strong></div>
            <div><span>Role</span><strong>{user.role.replaceAll('_', ' ')}</strong></div>
            <div><span>Account</span><StatusBadge value={user.is_active ? 'active' : 'inactive'} toneMap={{ active: 'green', inactive: 'rose' }} /></div>
          </div>
          <p className="muted-label">{idle > 0 ? `You are signed out automatically after ${idle} minutes without activity.` : 'Automatic sign out after inactivity is turned off for this deployment.'}</p>
        </Card>
        <Card>
          <SectionHeading title="Live service status" description="Read from the backend now, not from a stored claim." />
          <div className="readiness-list">
            <div>
              <Icon name="check" size={16} /><span>Backend and database readiness</span>
              {ready.loading && ready.data === null ? <StatusBadge value="checking" toneMap={{ checking: 'neutral' }} /> : <StatusBadge value={ready.data ? 'ready' : 'unavailable'} toneMap={{ ready: 'green', unavailable: 'rose' }} />}
            </div>
            {canSap && (
              <div>
                <Icon name="plug" size={16} /><span>SAP Business One integration</span>
                {sap.error ? <StatusBadge value="status unavailable" toneMap={{ 'status unavailable': 'amber' }} />
                  : !sap.data ? <StatusBadge value="checking" toneMap={{ checking: 'neutral' }} />
                  : !sap.data.enabled ? <StatusBadge value="disabled" toneMap={{ disabled: 'neutral' }} />
                  : !sap.data.configured ? <StatusBadge value="not configured" toneMap={{ 'not configured': 'amber' }} />
                  : <StatusBadge value={sap.data.live_connection_verified ? 'verified' : 'configured, not verified'} toneMap={{ verified: 'green', 'configured, not verified': 'blue' }} />}
              </div>
            )}
          </div>
          <div className="config-line"><span>API base</span><code>{API_BASE_URL}</code></div>
          <Notice tone="info" live="none">Database, SAP and AI provider credentials stay on the server. This browser only holds your session.</Notice>
        </Card>
      </div>

      <Card>
        <SectionHeading title="Your permissions" description="The server checks these on every request. Hiding a menu item is a convenience, not a control." />
        {user.permissions.length === 0 ? <p className="muted-label">No permissions are granted to this account.</p> : (
          <dl className="permission-groups">
            {groupPermissions(user.permissions).map(([domain, actions]) => (
              <div key={domain}><dt>{domain.replaceAll('_', ' ')}</dt><dd>{actions.map((a) => <code key={a}>{a}</code>)}</dd></div>
            ))}
          </dl>
        )}
      </Card>

      <Card>
        <SectionHeading title="Known limits of this deployment" description="Stated plainly so they can be planned for." />
        <ul className="plain-list">
          <li>Multi factor sign in and single sign on are not implemented. Access relies on passwords plus the session controls above.</li>
          <li>Rate limits are held in the memory of one API process. Run a single API worker until a shared limiter is added.</li>
          <li>Tax, treasury, budgeting, bank reconciliation, fraud, compliance and period close are reachable through AI Agents. They do not have dedicated workspaces yet.</li>
          <li>Live SAP synchronization has not been verified against a real SAP company by this software; use the SAP workspace to check the connection state.</li>
        </ul>
      </Card>

      <button type="button" className="logout-link" onClick={onSignOut}><Icon name="logout" size={16} /> Sign out of finance workspace</button>
    </div>
  )
}
