import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { BankPdfGuide, makeAccountReference } from './BankPdfGuide'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('exports only the account fields needed to map bank PDF rows to internal IDs', () => {
  const reference = makeAccountReference([{
    id: 7, name: 'Основная карта', currency: 'RUB', type: 'bank', archived: false,
    initial_balance_date: '2026-01-01', initial_balance_minor: 200_000,
    current_balance_minor: 180_000, version: 5,
  }], '2026-10-04T10:00:00.000Z')
  expect(reference).toEqual({
    format: 'budget-planner-account-reference-v1',
    exported_at: '2026-10-04T10:00:00.000Z',
    accounts: [{ account_id: 7, name: 'Основная карта', currency: 'RUB', type: 'bank', archived: false, initial_balance_date: '2026-01-01' }],
  })
  expect(JSON.stringify(reference)).not.toContain('balance_minor')
})

it('downloads the authenticated account list from the import guide', async () => {
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    expect(String(input)).toBe('/api/v1/accounts?include_archived=true')
    return new Response(JSON.stringify({ items: [{ id: 7, name: 'Основная карта', currency: 'RUB', type: 'bank', archived: false, initial_balance_date: '2026-01-01', current_balance_minor: 180_000 }] }), { headers: { 'content-type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  const createURL = vi.fn((_blob: Blob) => 'blob:accounts-export')
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createURL })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><BankPdfGuide /></QueryClientProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Скачать счета для ИИ' }))
  await waitFor(() => expect(createURL).toHaveBeenCalledOnce())
  const blob = createURL.mock.calls[0][0]
  const exported = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(blob)
  })
  expect(JSON.parse(exported).accounts).toEqual([{
    account_id: 7, name: 'Основная карта', currency: 'RUB', type: 'bank',
    archived: false, initial_balance_date: '2026-01-01',
  }])
  expect(click).toHaveBeenCalledOnce()
  expect(fetchMock).toHaveBeenCalledOnce()
})
