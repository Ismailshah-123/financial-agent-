/**
 * Minimal, safe CSV serialisation for report downloads. Values are written exactly
 * as the API returned them (decimal strings), so nothing is rounded or recomputed.
 */

const FORMULA_PREFIX = /^[=+\-@\t\r]/

/** Quotes a cell and neutralises spreadsheet formula injection (CWE-1236). */
export function csvCell(value: unknown): string {
  let text = value === null || value === undefined ? '' : String(value)
  // A leading apostrophe stops Excel/Sheets from evaluating the cell as a formula.
  // Plain negative numbers stay numeric: only non-numeric text gets the guard.
  if (FORMULA_PREFIX.test(text) && !/^-?\d+(\.\d+)?$/.test(text)) text = `'${text}`
  return /[",\n\r]/.test(text) || text !== String(value ?? '') ? `"${text.replaceAll('"', '""')}"` : text
}

export function toCsv(rows: unknown[][]): string {
  return `${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}\r\n`
}

export function downloadTextFile(filename: string, content: string, mime = 'text/csv;charset=utf-8'): void {
  const url = URL.createObjectURL(new Blob(['\uFEFF', content], { type: mime }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
