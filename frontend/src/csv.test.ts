import { describe, expect, it } from 'vitest'
import { csvCell, toCsv } from './csv'

describe('csv serialisation', () => {
  it('writes decimal strings exactly as given', () => {
    expect(toCsv([['1234567890123456789.10', '-0.005']])).toBe('1234567890123456789.10,-0.005\r\n')
  })
  it('quotes commas, quotes and newlines', () => {
    expect(csvCell('Acme, Inc.')).toBe('"Acme, Inc."')
    expect(csvCell('say "hi"')).toBe('"say ""hi"""')
    expect(csvCell('a\nb')).toBe('"a\nb"')
  })
  it('neutralises spreadsheet formula injection in text', () => {
    expect(csvCell('=HYPERLINK("http://evil")')).toBe('"\'=HYPERLINK(""http://evil"")"')
    expect(csvCell('+1+1')).toBe('"\'+1+1"')
    expect(csvCell('@SUM(A1)')).toBe('"\'@SUM(A1)"')
  })
  it('keeps negative numbers numeric', () => {
    expect(csvCell('-12.50')).toBe('-12.50')
  })
  it('renders null and undefined as empty cells', () => {
    expect(toCsv([[null, undefined, 'x']])).toBe(',,x\r\n')
  })
})
