import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { failed: boolean; reference: string }

/** Last line of defence: a rendering bug in one workspace must not blank the whole app. */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false, reference: '' }

  static getDerivedStateFromError(): State {
    return { failed: true, reference: `ui-${Date.now().toString(36)}` }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Detail stays in the browser console; nothing financial is sent anywhere.
    console.error('ui_render_error', this.state.reference, error, info.componentStack)
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children
    return (
      <div className="empty-state" role="alert">
        <div className="empty-icon" aria-hidden="true">!</div>
        <h3>This screen hit an unexpected problem</h3>
        <p>Your data was not changed. Reload the page to continue. If it keeps happening, quote reference {this.state.reference}.</p>
        <button type="button" className="button button-primary" onClick={() => window.location.reload()}>Reload page</button>
      </div>
    )
  }
}
