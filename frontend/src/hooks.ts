import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, isAbortError } from './api'

export interface AsyncState<T> {
  data: T | null
  error: ApiError | null
  /** True while a request is in flight (including reloads that keep showing previous data). */
  loading: boolean
  reload: () => void
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  return new ApiError(error instanceof Error ? error.message : 'Unexpected error.')
}

/**
 * Runs `fn` whenever `deps` change and when `reload()` is called.
 *
 * - The request receives an AbortSignal that is aborted on unmount, on a dependency
 *   change and on reload, so a slow older response can never overwrite a newer one.
 * - Previous data stays visible while a reload is in flight (no flash of empty UI).
 * - Cancellation is never surfaced as an error.
 */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: readonly unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    fnRef.current(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setData(result)
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted || isAbortError(caught)) return
        setError(toApiError(caught))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce((value) => value + 1), [])
  return { data, error, loading, reload }
}

export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs)
    return () => window.clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

export function useDocumentTitle(title: string): void {
  useEffect(() => {
    document.title = `${title} | Finance AI Control Center`
  }, [title])
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => typeof window.matchMedia === 'function' && window.matchMedia(query).matches)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const list = window.matchMedia(query)
    const update = () => setMatches(list.matches)
    update()
    list.addEventListener('change', update)
    return () => list.removeEventListener('change', update)
  }, [query])
  return matches
}
