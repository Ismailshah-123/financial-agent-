import type { ApiErrorLike, TokenResponse, User } from './types'

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
const DEFAULT_TIMEOUT_MS = 15000

/** Dispatched on `window` when the server refuses to renew the session. */
export const SESSION_EXPIRED_EVENT = 'finance:session-expired'

export interface FieldIssue {
  field: string
  message: string
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Pulls per-field problems out of the platform error body (`details.errors`)
 * or the framework's original `detail` array. */
export function fieldIssuesFromBody(body: unknown): FieldIssue[] {
  if (!isRecord(body)) return []
  const fromDetails = isRecord(body.details) && Array.isArray(body.details.errors) ? body.details.errors : null
  const source = fromDetails ?? (Array.isArray(body.detail) ? body.detail : [])
  const issues: FieldIssue[] = []
  for (const item of source) {
    if (!isRecord(item)) continue
    const message = typeof item.message === 'string' ? item.message : typeof item.msg === 'string' ? item.msg : ''
    if (!message) continue
    const field = typeof item.field === 'string'
      ? item.field
      : Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body' && part !== 'query').join('.') : ''
    issues.push({ field, message })
  }
  return issues.slice(0, 20)
}

export class ApiError extends Error implements ApiErrorLike {
  status: number
  body: unknown
  correlationId: string | null
  /** Stable machine-readable code from the backend (`error_code`), when present. */
  code: string | null
  retryAfterSeconds: number | null
  fieldErrors: FieldIssue[]
  /** True when the caller cancelled the request (navigation, unmount). Not a failure. */
  aborted: boolean

  constructor(
    message: string,
    status = 0,
    body: unknown = null,
    correlationId: string | null = null,
    extras: { retryAfterSeconds?: number | null; aborted?: boolean } = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.correlationId = correlationId
    this.code = isRecord(body) && typeof body.error_code === 'string' ? body.error_code : null
    this.retryAfterSeconds = extras.retryAfterSeconds ?? null
    this.fieldErrors = fieldIssuesFromBody(body)
    this.aborted = extras.aborted ?? false
  }
}

export function isAbortError(error: unknown): boolean {
  return error instanceof ApiError && error.aborted
}

interface RequestOptions {
  body?: unknown
  params?: Record<string, unknown>
  token?: string
  headers?: Record<string, string>
  signal?: AbortSignal
}

/** A mutation may only be replayed after a token refresh when the caller supplies
 * an idempotency key. Network/auth retries must never duplicate a financial action. */
export function canReplayAfterRefresh(method: string, headers?: Record<string, string>): boolean {
  if (SAFE_METHODS.has(method.toUpperCase())) return true
  return Object.entries(headers || {}).some(([name, value]) =>
    name.toLowerCase() === 'idempotency-key' && typeof value === 'string' && value.trim().length > 0,
  )
}

function getStoredTokens(): TokenResponse | null {
  try {
    const raw = sessionStorage.getItem('finance_tokens')
    return raw ? JSON.parse(raw) as TokenResponse : null
  } catch {
    return null
  }
}

function setStoredTokens(tokens: TokenResponse): void {
  sessionStorage.setItem('finance_tokens', JSON.stringify(tokens))
}

export function clearStoredSession(): void {
  sessionStorage.removeItem('finance_tokens')
  sessionStorage.removeItem('finance_user')
}

export function getStoredUser(): User | null {
  try {
    const raw = sessionStorage.getItem('finance_user')
    return raw ? JSON.parse(raw) as User : null
  } catch {
    return null
  }
}

function setStoredUser(user: User): void {
  sessionStorage.setItem('finance_user', JSON.stringify(user))
}

async function parseResponse(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) return null
  try {
    return await response.json()
  } catch {
    return null
  }
}

/** Turns an error body into one user-facing sentence. Internals are never echoed:
 * for server faults the correlation id is the reference support will ask for. */
export function messageFromBody(body: unknown, status: number, correlationId: string | null = null): string {
  if (isRecord(body)) {
    if (typeof body.detail === 'string' && body.detail) return body.detail
    if (typeof body.message === 'string' && body.message) {
      const issues = fieldIssuesFromBody(body)
      if (status === 422 && issues.length) {
        return `${body.message} ${issues.slice(0, 3).map((i) => (i.field ? `${i.field}: ${i.message}` : i.message)).join('; ')}`
      }
      return body.message
    }
    if (typeof body.error === 'string' && body.error) return body.error
    const issues = fieldIssuesFromBody(body)
    if (issues.length) return issues.slice(0, 3).map((i) => (i.field ? `${i.field}: ${i.message}` : i.message)).join('; ')
  }
  if (status >= 500) {
    return `The finance service could not complete the request.${correlationId ? ` Reference: ${correlationId}.` : ''}`
  }
  if (status === 429) return 'Too many requests. Wait a moment and try again.'
  if (status === 403) return 'Your role does not have permission to do this.'
  if (status === 404) return 'The requested record was not found.'
  if (status === 401) return 'Your session is not valid. Sign in again.'
  return `Request failed (${status}).`
}

function newCorrelationId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function parseRetryAfter(response: Response): number | null {
  const raw = response.headers.get('Retry-After')
  if (!raw) return null
  const seconds = Number(raw)
  return Number.isFinite(seconds) && seconds >= 0 ? Math.ceil(seconds) : null
}

async function rawRequest<T>(
  method: string,
  path: string,
  { body, params, token, headers: extraHeaders, signal }: RequestOptions = {},
): Promise<T> {
  const query = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  })

  const url = `${API_BASE_URL}${path}${query.toString() ? `?${query.toString()}` : ''}`
  const correlationId = newCorrelationId()
  const headers: Record<string, string> = { Accept: 'application/json', 'X-Correlation-ID': correlationId, ...(extraHeaders || {}) }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`

  const controller = new AbortController()
  const onCallerAbort = () => controller.abort()
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', onCallerAbort, { once: true })
  }
  let timedOut = false
  const timeoutId = window.setTimeout(() => { timedOut = true; controller.abort() }, DEFAULT_TIMEOUT_MS)
  const mutation = !SAFE_METHODS.has(method.toUpperCase())

  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'omit',
      signal: controller.signal,
    })
  } catch (error) {
    const wasAbort = error instanceof DOMException && error.name === 'AbortError'
    if (wasAbort && !timedOut) {
      throw new ApiError('The request was cancelled.', 0, null, correlationId, { aborted: true })
    }
    if (wasAbort) {
      throw new ApiError(
        mutation
          ? 'The request timed out and its outcome is unknown. Check the record\'s current status before trying again.'
          : 'The finance API request timed out. Please retry.',
        408,
        null,
        correlationId,
      )
    }
    throw new ApiError(
      mutation
        ? 'The finance API could not be reached and the outcome is unknown. Check the record\'s current status before trying again.'
        : 'The finance API is unreachable. Confirm the backend is running and CORS allows this frontend.',
      0,
      null,
      correlationId,
    )
  } finally {
    window.clearTimeout(timeoutId)
    signal?.removeEventListener('abort', onCallerAbort)
  }

  const responseCorrelationId = response.headers.get('X-Correlation-ID') || correlationId
  const data = await parseResponse(response)
  if (!response.ok) {
    const bodyCorrelation = isRecord(data) && typeof data.correlation_id === 'string' ? data.correlation_id : null
    const reference = bodyCorrelation || responseCorrelationId
    throw new ApiError(
      messageFromBody(data, response.status, reference),
      response.status,
      data,
      reference,
      { retryAfterSeconds: parseRetryAfter(response) },
    )
  }
  return data as T
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const tokens = await rawRequest<TokenResponse>('POST', '/auth/login', { body: { email, password } })
  setStoredTokens(tokens)
  return tokens
}

type RefreshOutcome = 'renewed' | 'rejected' | 'unavailable'

async function performRefresh(): Promise<RefreshOutcome> {
  const tokens = getStoredTokens()
  if (!tokens?.refresh_token) return 'rejected'
  try {
    const refreshed = await rawRequest<TokenResponse>('POST', '/auth/refresh', { body: { refresh_token: tokens.refresh_token } })
    setStoredTokens(refreshed)
    return 'renewed'
  } catch (error) {
    // Only an explicit refusal ends the session. A timeout, network fault or 5xx
    // is transient and must not sign the user out of in-flight work.
    if (error instanceof ApiError && (error.status === 401 || error.status === 403 || error.status === 422)) return 'rejected'
    return 'unavailable'
  }
}

let refreshInFlight: Promise<RefreshOutcome> | null = null

/** Concurrent 401s share ONE refresh call. With rotating refresh tokens a second
 * parallel refresh would present an already-used token and log the user out. */
function refreshSession(): Promise<RefreshOutcome> {
  if (!refreshInFlight) {
    refreshInFlight = performRefresh().finally(() => { refreshInFlight = null })
  }
  return refreshInFlight
}

function endSession(): void {
  clearStoredSession()
  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT))
}

async function request<T>(method: string, path: string, options: RequestOptions = {}, retry = true): Promise<T> {
  const tokens = getStoredTokens()
  if (!tokens?.access_token) throw new ApiError('Not authenticated.', 401)
  const usedToken = tokens.access_token
  try {
    return await rawRequest<T>(method, path, { ...options, token: usedToken })
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401 || !retry) {
      if (error instanceof ApiError && error.status === 401 && !retry) endSession()
      throw error
    }

    // Another request may already have renewed the session while this one was in flight.
    const current = getStoredTokens()?.access_token
    const alreadyRenewed = Boolean(current && current !== usedToken)
    const outcome = alreadyRenewed ? 'renewed' : await refreshSession()
    if (outcome === 'rejected') {
      endSession()
      throw error
    }
    if (outcome === 'unavailable') throw error

    if (canReplayAfterRefresh(method, options.headers)) {
      return request<T>(method, path, options, false)
    }
    // Keep the refreshed session, but do not replay a non-idempotent command.
    // The user must inspect current state before deliberately trying again.
    throw new ApiError(
      'Your session was renewed, but this operation was not replayed to prevent a duplicate action. Refresh the record and confirm its current status before retrying.',
      401,
      error.body,
      error.correlationId,
    )
  }
}

export const api = {
  get: <T = unknown>(path: string, params?: Record<string, unknown>, signal?: AbortSignal) =>
    request<T>('GET', path, { params, signal }),
  post: <T = unknown>(path: string, body?: unknown, headers?: Record<string, string>, signal?: AbortSignal) =>
    request<T>('POST', path, { body, headers, signal }),
  patch: <T = unknown>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>('PATCH', path, { body, signal }),
}

export async function checkBackendReadiness(signal?: AbortSignal): Promise<boolean> {
  try {
    await rawRequest('GET', '/health/ready', { signal })
    return true
  } catch {
    return false
  }
}

export async function logout(): Promise<void> {
  const tokens = getStoredTokens()
  clearStoredSession()
  if (!tokens?.refresh_token) return
  try {
    await rawRequest('POST', '/auth/logout', { body: { refresh_token: tokens.refresh_token } })
  } catch {
    // Local logout must still complete even if the server is unavailable.
  }
}

export async function getCurrentUser(signal?: AbortSignal): Promise<User> {
  const user = await request<User>('GET', '/auth/me', { signal })
  setStoredUser(user)
  return user
}
