import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { formatMoney } from '../lib/format'
import { AccountsPage } from './Accounts'

afterEach(() => vi.unstubAllGlobals())

it('shows active and archived account balances in the overall total', async () => {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
    items: [
      { id: 1, name: 'Карта', type: 'bank', initial_balance_minor: 100_000, initial_balance_date: '2026-01-01', current_balance_minor: 120_000, archived: false },
      { id: 2, name: 'Накопительный', type: 'savings', initial_balance_minor: 20_000, initial_balance_date: '2026-01-01', current_balance_minor: 50_000, archived: false },
      { id: 3, name: 'Старый счёт', type: 'cash', initial_balance_minor: 10_000, initial_balance_date: '2026-01-01', current_balance_minor: 5_000, archived: true },
    ],
    total: 3,
  }), { headers: { 'content-type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><AccountsPage/></MemoryRouter></QueryClientProvider>)

  expect(await screen.findByText('Старый счёт')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/accounts?include_archived=true', expect.objectContaining({ method: 'GET' }))
  const matchesMoney = (amount: number) => (content: string) => content.replace(/\s/g, ' ') === formatMoney(amount).replace(/\s/g, ' ')
  expect(screen.getByText(matchesMoney(175_000))).toBeInTheDocument()
  expect(screen.getByText(matchesMoney(170_000))).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Управлять счетами/ })).toHaveAttribute('href', '/settings?tab=accounts')
  expect(screen.getByRole('link', { name: /Операции и переводы/ })).toHaveAttribute('href', '/transactions')
})
