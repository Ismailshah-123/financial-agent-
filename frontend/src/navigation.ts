import { useEffect, useState } from 'react'

const LOCATION_EVENT = 'finance:locationchange'

export interface LocationState {
  pathname: string
  search: string
}

function readLocation(): LocationState {
  return { pathname: window.location.pathname, search: window.location.search }
}

/** Client-side navigation without a full page load. */
export function navigate(path: string, options: { replace?: boolean } = {}): void {
  const current = `${window.location.pathname}${window.location.search}`
  if (path === current) return
  if (options.replace) window.history.replaceState({}, '', path)
  else window.history.pushState({}, '', path)
  window.dispatchEvent(new Event(LOCATION_EVENT))
}

export function useLocation(): LocationState {
  const [location, setLocation] = useState<LocationState>(readLocation)
  useEffect(() => {
    const update = () => setLocation(readLocation())
    window.addEventListener('popstate', update)
    window.addEventListener(LOCATION_EVENT, update)
    return () => {
      window.removeEventListener('popstate', update)
      window.removeEventListener(LOCATION_EVENT, update)
    }
  }, [])
  return location
}
