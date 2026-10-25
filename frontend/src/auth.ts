import { useCallback, useEffect, useRef, useState } from 'react'
import {
  SESSION_EXPIRED_EVENT,
  clearStoredSession,
  getCurrentUser,
  login as apiLogin,
  logout as apiLogout,
} from './api'
import type { Permission, User } from './types'

export function hasPermission(user: User | null, permission: Permission): boolean {
  return Boolean(user?.permissions?.includes(permission))
}

export function hasSession(): boolean {
  return Boolean(sessionStorage.getItem('finance_tokens'))
}

/** Minutes of inactivity before the browser session is ended. 0 disables the timer. */
export function idleTimeoutMinutes(): number {
  const raw = Number(import.meta.env.VITE_IDLE_TIMEOUT_MINUTES ?? 30)
  return Number.isFinite(raw) && raw >= 0 ? raw : 30
}

export type SignOutReason = 'user' | 'expired' | 'idle'

const NOTICES: Record<SignOutReason, string | null> = {
  user: null,
  expired: 'Your session expired. Sign in again to continue.',
  idle: 'You were signed out after a period of inactivity.',
}

export interface AuthState {
  user: User | null
  loading: boolean
  /** Why the user is looking at the sign-in screen, when it was not their choice. */
  notice: string | null
  signIn: (email: string, password: string) => Promise<User>
  signOut: (reason?: SignOutReason) => void
  can: (permission: Permission) => boolean
}

export function useAuth(): AuthState {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState<boolean>(hasSession())
  const [notice, setNotice] = useState<string | null>(null)
  const userRef = useRef<User | null>(null)
  userRef.current = user

  // Server-confirmed identity: cached user data is never trusted on its own, and
  // nothing protected renders until /auth/me has answered.
  useEffect(() => {
    const controller = new AbortController()
    if (!hasSession()) {
      setLoading(false)
      return () => controller.abort()
    }
    getCurrentUser(controller.signal)
      .then((nextUser) => { if (!controller.signal.aborted) setUser(nextUser) })
      .catch(() => { if (!controller.signal.aborted) setUser(null) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  const signOut = useCallback((reason: SignOutReason = 'user') => {
    void apiLogout()
    clearStoredSession()
    setUser(null)
    setNotice(NOTICES[reason])
  }, [])

  // The API client ends the session when the server refuses to renew it.
  useEffect(() => {
    const onExpired = () => {
      if (!userRef.current) return
      clearStoredSession()
      setUser(null)
      setNotice(NOTICES.expired)
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
  }, [])

  // Idle timeout: finance data should not stay on screen on an unattended device.
  useEffect(() => {
    const minutes = idleTimeoutMinutes()
    if (!user || minutes === 0) return
    let timer = window.setTimeout(() => signOut('idle'), minutes * 60_000)
    let lastReset = Date.now()
    const onActivity = () => {
      const now = Date.now()
      if (now - lastReset < 5_000) return // throttle
      lastReset = now
      window.clearTimeout(timer)
      timer = window.setTimeout(() => signOut('idle'), minutes * 60_000)
    }
    const events: (keyof WindowEventMap)[] = ['pointerdown', 'keydown', 'scroll', 'touchstart']
    events.forEach((name) => window.addEventListener(name, onActivity, { passive: true }))
    return () => {
      window.clearTimeout(timer)
      events.forEach((name) => window.removeEventListener(name, onActivity))
    }
  }, [user, signOut])

  const signIn = useCallback(async (email: string, password: string): Promise<User> => {
    await apiLogin(email, password)
    const nextUser = await getCurrentUser()
    setNotice(null)
    setUser(nextUser)
    return nextUser
  }, [])

  const can = useCallback((permission: Permission) => hasPermission(user, permission), [user])

  return { user, loading, notice, signIn, signOut, can }
}
