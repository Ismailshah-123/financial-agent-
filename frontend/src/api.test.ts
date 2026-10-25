import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError, SESSION_EXPIRED_EVENT, api, canReplayAfterRefresh, clearStoredSession, fieldIssuesFromBody, getStoredUser,
  isAbortError, login, messageFromBody,
} from './api'

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } })
}

function seedSession(access = 'access-1', refresh = 'refresh-1'): void {
  sessionStorage.setItem('finance_tokens', JSON.stringify({ access_token: access, refresh_token: refresh, token_type: 'bearer', expires_in: 1800 }))
}

function authHeader(init?: RequestInit): string {
  return String((init?.headers as Record<string, string>)?.Authorization ?? '')
}

describe('api error and session handling', () => {
  it('preserves correlation and HTTP status for normalized errors', () => {
    const error = new ApiError('Forbidden', 403, { error_code: 'insufficient_permissions' }, 'corr-123')
    expect(error.status).toBe(403)
    expect(error.correlationId).toBe('corr-123')
    expect(error.code).toBe('insufficient_permissions')
  })
  it('clears only finance session keys', () => {
    sessionStorage.setItem('finance_tokens', '{}')
    sessionStorage.setItem('finance_user', '{}')
    clearStoredSession()
    expect(getStoredUser()).toBeNull()
  })
})

describe('error messages', () => {
  it('uses a string detail as-is', () => {
    expect(messageFromBody({ detail: 'Invoice is locked.' }, 409)).toBe('Invoice is locked.')
  })
  it('lists field problems for validation errors', () => {
    const body = { message: 'The request was not valid.', details: { errors: [{ field: 'currency', message: 'String should have at least 3 characters' }] } }
    expect(messageFromBody(body, 422)).toContain('currency: String should have at least 3 characters')
  })
  it('reads the framework detail array', () => {
    const body = { detail: [{ loc: ['query', 'page'], msg: 'Input should be greater than 0' }] }
    expect(fieldIssuesFromBody(body)).toEqual([{ field: 'page', message: 'Input should be greater than 0' }])
    expect(messageFromBody(body, 422)).toBe('page: Input should be greater than 0')
  })
  it('never echoes server internals for 5xx and shows the reference instead', () => {
    const message = messageFromBody({ trace: 'psycopg2.errors.UndefinedTable' }, 500, 'corr-9')
    expect(message).toContain('Reference: corr-9')
    expect(message).not.toContain('psycopg2')
  })
  it('has plain defaults for common statuses', () => {
    expect(messageFromBody(null, 403)).toMatch(/permission/)
    expect(messageFromBody(null, 404)).toMatch(/not found/)
    expect(messageFromBody(null, 429)).toMatch(/Too many requests/)
  })
})

describe('auth refresh replay safety', () => {
  it('replays safe read methods after refresh', () => {
    expect(canReplayAfterRefresh('GET')).toBe(true)
    expect(canReplayAfterRefresh('HEAD')).toBe(true)
  })
  it('does not replay financial mutations without an idempotency key', () => {
    expect(canReplayAfterRefresh('POST')).toBe(false)
    expect(canReplayAfterRefresh('PATCH')).toBe(false)
  })
  it('allows a mutation replay only when a non-empty idempotency key is provided', () => {
    expect(canReplayAfterRefresh('POST', { 'Idempotency-Key': 'approval-123' })).toBe(true)
    expect(canReplayAfterRefresh('POST', { 'Idempotency-Key': ' ' })).toBe(false)
  })
})

describe('request pipeline', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    sessionStorage.clear()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('stores tokens on login and sends them as a bearer header', async () => {
    fetchMock.mockResolvedValueOnce(json({ access_token: 'a1', refresh_token: 'r1', token_type: 'bearer', expires_in: 1800 }))
    await login('a@b.co', 'secret-pass')
    fetchMock.mockResolvedValueOnce(json({ ok: true }))
    await api.get('/aging/summary')
    expect(authHeader(fetchMock.mock.calls[1][1])).toBe('Bearer a1')
  })

  it('shares ONE refresh between concurrent 401s and retries each read with the new token', async () => {
    seedSession('stale', 'refresh-1')
    let refreshCalls = 0
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/auth/refresh')) {
        refreshCalls += 1
        await new Promise((resolve) => setTimeout(resolve, 5))
        return json({ access_token: 'fresh', refresh_token: 'refresh-2', token_type: 'bearer', expires_in: 1800 })
      }
      return authHeader(init) === 'Bearer fresh' ? json({ ok: String(url) }) : json({ message: 'expired' }, 401)
    })
    const results = await Promise.all([api.get('/a'), api.get('/b'), api.get('/c')])
    expect(refreshCalls).toBe(1)
    expect(results).toHaveLength(3)
    expect(JSON.parse(sessionStorage.getItem('finance_tokens') as string).refresh_token).toBe('refresh-2')
  })

  it('ends the session and announces it when the server refuses the refresh token', async () => {
    seedSession('stale', 'revoked')
    const onExpired = vi.fn()
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    fetchMock.mockImplementation(async (url: string) => (String(url).endsWith('/auth/refresh') ? json({ message: 'revoked' }, 401) : json({ message: 'expired' }, 401)))
    await expect(api.get('/aging/summary')).rejects.toMatchObject({ status: 401 })
    expect(sessionStorage.getItem('finance_tokens')).toBeNull()
    expect(onExpired).toHaveBeenCalledTimes(1)
    window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
  })

  it('keeps the session when the refresh endpoint is merely unavailable', async () => {
    seedSession('stale', 'refresh-1')
    fetchMock.mockImplementation(async (url: string) => (String(url).endsWith('/auth/refresh') ? json({ message: 'down' }, 503) : json({ message: 'expired' }, 401)))
    await expect(api.get('/aging/summary')).rejects.toMatchObject({ status: 401 })
    expect(sessionStorage.getItem('finance_tokens')).not.toBeNull()
  })

  it('does not replay a mutation after a refresh unless it carries an idempotency key', async () => {
    seedSession('stale', 'refresh-1')
    const seen: string[] = []
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/auth/refresh')) return json({ access_token: 'fresh', refresh_token: 'r2', token_type: 'bearer', expires_in: 1800 })
      seen.push(`${init?.method} ${url} ${authHeader(init)}`)
      return authHeader(init) === 'Bearer fresh' ? json({ ok: true }) : json({ message: 'expired' }, 401)
    })
    await expect(api.post('/approval-requests/1/approve', {})).rejects.toThrow(/not replayed/)
    expect(seen).toHaveLength(1) // sent once with the stale token, never re-sent

    seedSession('stale', 'refresh-1')
    seen.length = 0
    await expect(api.post('/approval-requests/1/execute', undefined, { 'Idempotency-Key': 'k-1' })).resolves.toEqual({ ok: true })
    expect(seen).toHaveLength(2)
  })

  it('says the outcome is unknown when a mutation cannot be confirmed', async () => {
    seedSession()
    fetchMock.mockRejectedValue(new TypeError('network down'))
    await expect(api.post('/approval-requests/1/execute')).rejects.toThrow(/outcome is unknown/)
    await expect(api.get('/aging/summary')).rejects.toThrow(/unreachable/)
  })

  it('reports cancellation separately from failure', async () => {
    seedSession()
    const controller = new AbortController()
    controller.abort()
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.signal?.aborted) throw new DOMException('aborted', 'AbortError')
      return json({})
    })
    const error = await api.get('/aging/summary', undefined, controller.signal).catch((caught: unknown) => caught)
    expect(isAbortError(error)).toBe(true)
  })

  it('surfaces the correlation id and Retry-After from the server', async () => {
    seedSession()
    fetchMock.mockResolvedValue(json({ message: 'Slow down', correlation_id: 'c-77' }, 429, { 'Retry-After': '12' }))
    const error = await api.get('/aging/summary').catch((caught: unknown) => caught) as ApiError
    expect(error.status).toBe(429)
    expect(error.correlationId).toBe('c-77')
    expect(error.retryAfterSeconds).toBe(12)
  })

  it('rejects calls without a session instead of sending an anonymous request', async () => {
    await expect(api.get('/aging/summary')).rejects.toMatchObject({ status: 401 })
    expect(fetchMock).toHaveBeenCalledTimes(0)
  })
})
