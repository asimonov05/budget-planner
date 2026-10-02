import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { AccountsPage } from './Accounts'

afterEach(() => { vi.unstubAllGlobals() })

it('shows a manually converted estimate and keeps each account in its own currency', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === '/api/v1/accounts?include_archived=true') return new Response(JSON.stringify({
      currency_display_mode: 'converted', base_currency: 'RUB', items: [
        { id: 1, name: 'Рубли', type: 'bank', currency: 'RUB', initial_balance_date: '2026-01-01', initial_balance_minor: 100_000, current_balance_minor: 100_000, archived: false },
        { id: 2, name: 'Доллары', type: 'bank', currency: 'USD', initial_balance_date: '2026-01-01', initial_balance_minor: 10_000, current_balance_minor: 10_000, archived: false },
      ], total: 2,
    }), { headers: { 'content-type': 'application/json' } })
    if (path === '/api/v1/accounts/converted-total') return new Response(JSON.stringify({
      currency: 'RUB', total_minor: 900_000, rate_source: 'manual', indicative: true,
    }), { headers: { 'content-type': 'application/json' } })
    throw new Error(`Unexpected request: ${path}`)
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<MemoryRouter><QueryClientProvider client={client}><AccountsPage /></QueryClientProvider></MemoryRouter>)
  expect(await screen.findByText('Ориентировочно всего')).toBeInTheDocument()
  expect(screen.getByText(/9\s*000\s*₽/)).toBeInTheDocument()
  expect(screen.getByText('Доллары')).toBeInTheDocument()
  expect(screen.getAllByText(/100\s*\$/).length).toBeGreaterThan(0)
})

it('points to rate settings when a required manual rate is missing', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === '/api/v1/accounts?include_archived=true') return new Response(JSON.stringify({
      currency_display_mode: 'converted', base_currency: 'RUB', items: [], total: 0,
    }), { headers: { 'content-type': 'application/json' } })
    if (path === '/api/v1/accounts/converted-total') return new Response(JSON.stringify({
      detail: 'Задайте курсы в настройках: USD',
    }), { status: 409, headers: { 'content-type': 'application/json' } })
    throw new Error(`Unexpected request: ${path}`)
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<MemoryRouter><QueryClientProvider client={client}><AccountsPage /></QueryClientProvider></MemoryRouter>)
  expect(await screen.findByText(/Задайте курсы в настройках: USD/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Задать курсы' })).toHaveAttribute('href', '/settings?tab=currencies')
})
