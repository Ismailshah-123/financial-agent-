import '@testing-library/jest-dom/vitest'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApiError } from '../api'
import Login from './Login'

describe('Login', () => {
  it('renders an accessible sign-in form without relying on backend data', () => {
    render(<Login onLogin={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByLabelText('Email address')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /continue to workspace/i })).toBeInTheDocument()
  })

  it('explains why the user was signed out', () => {
    render(<Login onLogin={vi.fn()} notice="Your session expired. Sign in again to continue." />)
    expect(screen.getByRole('status')).toHaveTextContent(/session expired/i)
  })

  it('shows a generic message for bad credentials and never echoes server detail', async () => {
    const onLogin = vi.fn().mockRejectedValue(new ApiError('internal detail', 401))
    render(<Login onLogin={onLogin} />)
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'a@b.co' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong-password' } })
    fireEvent.click(screen.getByRole('button', { name: /continue to workspace/i }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('The email or password is not correct.'))
    expect(screen.queryByText(/internal detail/)).not.toBeInTheDocument()
  })

  it('reports the retry delay when rate limited', async () => {
    const onLogin = vi.fn().mockRejectedValue(new ApiError('slow down', 429, null, null, { retryAfterSeconds: 30 }))
    render(<Login onLogin={onLogin} />)
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'a@b.co' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'whatever-1' } })
    fireEvent.click(screen.getByRole('button', { name: /continue to workspace/i }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Try again in 30 seconds'))
  })

  it('uses plain wording when the backend cannot be reached', async () => {
    const onLogin = vi.fn().mockRejectedValue(new ApiError('The finance API could not be reached and the outcome is unknown.', 0))
    render(<Login onLogin={onLogin} />)
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'a@b.co' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'whatever-1' } })
    fireEvent.click(screen.getByRole('button', { name: /continue to workspace/i }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('sign in service could not be reached'))
    expect(screen.queryByText(/outcome is unknown/)).not.toBeInTheDocument()
  })
})
