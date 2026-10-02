import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { CurrencySettings } from './CurrencySettings'

function json(body: unknown) { return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } }) }

afterEach(() => { vi.unstubAllGlobals() })

it('saves display mode and a manually chosen rate; the CBR value is only a suggestion', async () => {
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input)
    if (path === '/api/v1/settings' && init?.method === 'PATCH') return json({ currency: 'RUB', currency_display_mode: 'converted', version: 2 })
    if (path === '/api/v1/settings') return json({ currency: 'RUB', currency_display_mode: 'separate', version: 1 })
    if (path === '/api/v1/currencies/display-rates/USD' && init?.method === 'PUT') return json({ from_currency: 'USD', to_currency: 'RUB', rate: '81.500000000000', version: 2 })
    if (path === '/api/v1/currencies/display-rates') return json({ base_currency: 'RUB', version: 1, items: [{ from_currency: 'USD', to_currency: 'RUB', rate: null, updated_on: null, required: true }] })
    if (path.startsWith('/api/v1/currencies/quote?')) return json({ from_currency: 'USD', to_currency: 'RUB', rate: '80', effective_date: '2026-10-02', source: 'CBR', indicative: true })
    if (path === '/api/v1/currencies') return json({ items: [
      { code: 'RUB', name: 'Российский рубль', minor_digits: 2, popular: true },
      { code: 'USD', name: 'Доллар США', minor_digits: 2, popular: true },
    ] })
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><CurrencySettings /></QueryClientProvider>)

  expect(await screen.findByText(/курс не задан/)).toBeInTheDocument()
  await screen.findByText(/1 USD ≈ 80 RUB/)
  expect(screen.getByLabelText('Курс: 1 USD в RUB')).toHaveValue('')
  fireEvent.click(screen.getByRole('button', { name: 'Подставить в поле выше' }))
  expect(screen.getByLabelText('Курс: 1 USD в RUB')).toHaveValue('80')
  fireEvent.change(screen.getByLabelText('Курс: 1 USD в RUB'), { target: { value: '81,5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить курс' }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/currencies/display-rates/USD' && init?.method === 'PUT')).toBe(true))
  const [, rateRequest] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/currencies/display-rates/USD' && init?.method === 'PUT')!
  expect(JSON.parse(String(rateRequest?.body))).toEqual({ rate: '81.5', version: 1 })

  fireEvent.change(screen.getByLabelText('Баланс и прогноз'), { target: { value: 'converted' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить способ показа' }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/settings' && init?.method === 'PATCH')).toBe(true))
  const [, settingsRequest] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/settings' && init?.method === 'PATCH')!
  expect(JSON.parse(String(settingsRequest?.body))).toEqual({ currency_display_mode: 'converted', version: 1 })
})
