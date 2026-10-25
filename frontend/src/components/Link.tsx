import type { MouseEvent, ReactElement, ReactNode } from 'react'
import { navigate } from '../navigation'

interface LinkProps {
  to: string
  children: ReactNode
  className?: string
  current?: boolean
  onNavigate?: () => void
  title?: string
  'aria-label'?: string
}

/** A real anchor (so it can be opened in a new tab, copied and read by assistive tech)
 * that navigates in-app on a plain click. */
export default function Link({ to, children, className, current, onNavigate, title, 'aria-label': ariaLabel }: LinkProps): ReactElement {
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    navigate(to)
    onNavigate?.()
  }
  return (
    <a href={to} className={className} onClick={onClick} aria-current={current ? 'page' : undefined} title={title} aria-label={ariaLabel}>
      {children}
    </a>
  )
}
