import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AnalyticsPage } from './Analytics'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
}

describe('analytics category totals', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
    fetchMock.mockImplementation(async (input) => {
      const path = String(input)
      if (path === '/api/v1/accounts?include_archived=true') {
        return jsonResponse({ items: [{ id: 1, currency: 'RUB' }], base_currency: 'RUB', currency_display_mode: 'separate' })
      }
      if (path.startsWith('/api/v1/forecast?')) {
        return jsonResponse({ currency: 'RUB', months: [
          { month: '2026-09', income: 0, expense: 0, c_end: 0, r_end: 0, f_end: 0, category_details: [
            { category_id: 3, forecast_minor: '80000' },
            { category_id: 2, forecast_minor: '28190' },
          ] },
          { month: '2026-10', income: 0, expense: 0, c_end: 0, r_end: 0, f_end: 0, category_details: [
            { category_id: 3, forecast_minor: '80000' },
            { category_id: 2, forecast_minor: '44898' },
          ] },
        ] })
      }
      if (path === '/api/v1/categories?include_archived=true') {
        return jsonResponse({ items: [
          { id: 3, name: 'Кафе, рестораны' },
          { id: 2, name: 'Магазины' },
        ] })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('adds numeric-string minor units instead of concatenating them', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><AnalyticsPage /></QueryClientProvider>)

    const cafe = await screen.findByText('Кафе, рестораны')
    const shops = screen.getByText('Магазины')
    expect(cafe.parentElement).toHaveTextContent(/1\s*600\s*₽/)
    expect(shops.parentElement).toHaveTextContent(/730,88\s*₽/)
  })
})
