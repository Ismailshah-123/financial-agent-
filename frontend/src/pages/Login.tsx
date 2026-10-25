import { useState, type FormEvent, type ReactElement } from 'react'
import { ApiError } from '../api'
import { Icon } from '../components/Icons'
import { BrandMark, Button, Notice } from '../components/ui'
import type { User } from '../types'

interface LoginProps {
  onLogin: (email: string, password: string) => Promise<User>
  /** Why the user was signed out, when it was not their own choice. */
  notice?: string | null
}

export default function Login({ onLogin, notice = null }: LoginProps): ReactElement {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (loading) return
    setError('')
    setLoading(true)
    try {
      await onLogin(email.trim(), password)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setError('The email or password is not correct.')
      else if (err instanceof ApiError && err.status === 429) {
        setError(`Too many sign-in attempts.${err.retryAfterSeconds ? ` Try again in ${err.retryAfterSeconds} seconds.` : ' Wait a moment and try again.'}`)
      } else if (err instanceof ApiError && (err.status === 0 || err.status === 408)) {
        // Signing in changes nothing financial, so the generic "outcome unknown" wording would only alarm.
        setError('The sign in service could not be reached. Check that the backend is running, then try again.')
      } else setError(err instanceof Error ? err.message : 'Unable to sign in.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-ambient" aria-hidden="true"><span /><span /><span /></div>
      <main className="login-panel">
        <div className="login-brand"><BrandMark /><span className="secure-pill"><Icon name="lock" size={13} /> Private finance workspace</span></div>
        <div className="login-copy">
          <div className="eyebrow">Vertex Data Systems</div>
          <h1>Finance operations, with intelligence built in.</h1>
          <p>A focused workspace for AI-assisted finance decisions, human approvals, reporting, and SAP Business One workflows.</p>
          <ul className="login-points">
            <li>Every amount stays in its own currency. Nothing is converted or blended.</li>
            <li>AI recommends and people approve. Approving never moves money by itself.</li>
            <li>SAP shows as connected only after a real read from SAP has succeeded.</li>
          </ul>
        </div>
        <form className="login-card" onSubmit={submit} noValidate={false}>
          <div className="login-card-heading">
            <div><h2>Sign in</h2><p>Use your finance platform credentials.</p></div>
            <span className="shield" aria-hidden="true"><Icon name="lock" size={18} /></span>
          </div>
          {notice && <Notice tone="warning" icon="alert">{notice}</Notice>}
          <label className="field">
            <span>Email address</span>
            <input autoComplete="username" type="email" inputMode="email" placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <div className="field">
            <label htmlFor="login-password">Password</label>
            <span className="password-wrap">
              <input id="login-password" autoComplete="current-password" type={showPassword ? 'text' : 'password'} placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              <button type="button" className="password-toggle" aria-pressed={showPassword} aria-label="Show password" onClick={() => setShowPassword((value) => !value)}>
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </span>
          </div>
          {error && <div className="inline-error" role="alert"><Icon name="alert" size={16} />{error}</div>}
          <Button type="submit" disabled={loading} icon="arrow">{loading ? 'Signing in…' : 'Continue to workspace'}</Button>
          <p className="login-note">Your session lives in this browser tab only and ends when you sign out or stay inactive. Authorization is enforced by the finance API on every request.</p>
        </form>
        <div className="login-footer"><span>© 2026 Vertex Data Systems</span><span>Enterprise finance control</span></div>
      </main>
      <div className="login-visual" aria-hidden="true">
        <div className="visual-orbit orbit-a" /><div className="visual-orbit orbit-b" />
        <div className="visual-core"><span className="core-ring" /><span className="core-v">V</span></div>
        <div className="visual-caption"><span>AI Finance Layer</span><strong>AP · AR · TAX · RISK · SAP</strong></div>
      </div>
    </div>
  )
}
