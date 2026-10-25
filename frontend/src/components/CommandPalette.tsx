import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactElement } from 'react'
import { api } from '../api'
import { buildNavigationCommands, filterCommands } from '../commands'
import { useAsync, useDebouncedValue } from '../hooks'
import { navigate } from '../navigation'
import { buildPath } from '../router'
import type { Paginated } from '../types'
import { Icon } from './Icons'

interface Entry {
  id: string
  group: string
  label: string
  hint: string
  path: string
  icon: string
}

interface CustomerHit { customer_id: string; customer_name: string }
interface VendorHit { vendor_id: string; vendor_name: string }
interface RecordHits { customers: Paginated<CustomerHit> | null; vendors: Paginated<VendorHit> | null }

/** Ctrl or Cmd + K. Jump to any workspace, or find a real customer or vendor by name. */
export default function CommandPalette({ can }: { can: (permission: string) => boolean }): ReactElement {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const dialogRef = useRef<HTMLDialogElement | null>(null)
  const opener = useRef<Element | null>(null)
  const listId = useId()
  const debounced = useDebouncedValue(query.trim(), 250)
  const canCustomers = can('ar_invoice:read')
  const canVendors = can('invoice:read')

  const hits = useAsync<RecordHits | null>(
    async (signal) => {
      if (!open || debounced.length < 2) return null
      const [customers, vendors] = await Promise.all([
        canCustomers ? api.get<Paginated<CustomerHit>>('/aging/customers', { page: 1, page_size: 5, search: debounced }, signal) : Promise.resolve(null),
        canVendors ? api.get<Paginated<VendorHit>>('/ap-priority/vendors', { page: 1, page_size: 5, search: debounced }, signal) : Promise.resolve(null),
      ])
      return { customers, vendors }
    },
    [open, debounced, canCustomers, canVendors],
  )

  const entries = useMemo<Entry[]>(() => {
    const pages: Entry[] = filterCommands(buildNavigationCommands(can), query).map((command) => ({
      id: command.id, group: 'Go to', label: command.label, hint: command.hint, path: command.path, icon: command.icon,
    }))
    const customers: Entry[] = (hits.data?.customers?.items ?? []).map((row) => ({
      id: `customer:${row.customer_id}`, group: 'Customers', label: row.customer_name, hint: 'Open customer detail', path: buildPath('customer', { id: row.customer_id }), icon: 'users',
    }))
    const vendors: Entry[] = (hits.data?.vendors?.items ?? []).map((row) => ({
      id: `vendor:${row.vendor_id}`, group: 'Vendors', label: row.vendor_name, hint: 'Open vendor detail', path: buildPath('vendor', { id: row.vendor_id }), icon: 'wallet',
    }))
    return [...pages, ...customers, ...vendors]
  }, [can, query, hits.data])

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen((value) => !value)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) {
      opener.current = document.activeElement
      setQuery('')
      setActive(0)
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
    } else if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
      if (opener.current instanceof HTMLElement) opener.current.focus()
    }
  }, [open])

  useEffect(() => { setActive(0) }, [query, entries.length])

  function choose(entry: Entry | undefined): void {
    if (!entry) return
    setOpen(false)
    navigate(entry.path)
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive((value) => Math.min(entries.length - 1, value + 1)) }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setActive((value) => Math.max(0, value - 1)) }
    else if (event.key === 'Home') { event.preventDefault(); setActive(0) }
    else if (event.key === 'End') { event.preventDefault(); setActive(Math.max(0, entries.length - 1)) }
    else if (event.key === 'Enter') { event.preventDefault(); choose(entries[active]) }
  }

  const searching = open && debounced.length >= 2 && hits.loading
  let lastGroup = ''

  return (
    <>
      <button type="button" className="palette-trigger" onClick={() => setOpen(true)} aria-label="Open quick search" aria-keyshortcuts="Control+K Meta+K">
        <Icon name="search" size={15} />
        <span>Quick search</span>
        <kbd>Ctrl K</kbd>
      </button>
      <dialog ref={dialogRef} className="palette" aria-label="Quick search" onClose={() => setOpen(false)}>
        <div className="palette-input">
          <Icon name="search" size={17} />
          <input
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={entries[active] ? `${listId}-${active}` : undefined}
            aria-label="Search workspaces, customers and vendors"
            placeholder="Go to a workspace, or type a customer or vendor name"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            autoComplete="off"
            spellCheck={false}
          />
          <kbd>Esc</kbd>
        </div>
        <ul id={listId} role="listbox" aria-label="Results" className="palette-list">
          {entries.map((entry, index) => {
            const heading = entry.group !== lastGroup
            lastGroup = entry.group
            return (
              <li key={entry.id} role="presentation">
                {heading && <div className="palette-group" role="presentation">{entry.group}</div>}
                <div
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={index === active}
                  className={`palette-item ${index === active ? 'active' : ''}`}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(entry)}
                >
                  <Icon name={entry.icon} size={16} />
                  <span><strong>{entry.label}</strong>{entry.hint && <small>{entry.hint}</small>}</span>
                </div>
              </li>
            )
          })}
        </ul>
        {entries.length === 0 && !searching && <p className="palette-empty">Nothing matches &ldquo;{query.trim()}&rdquo;.</p>}
        <p className="palette-status" role="status" aria-live="polite">
          {searching ? 'Searching customers and vendors…' : hits.error ? 'Customer and vendor search is unavailable right now.' : `${entries.length} result${entries.length === 1 ? '' : 's'}`}
        </p>
      </dialog>
    </>
  )
}
