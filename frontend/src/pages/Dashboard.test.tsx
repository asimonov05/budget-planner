import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DashboardPage } from './Dashboard'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
}

describe('dashboard month closing', () => {
  const fetchMock = vi.fn<typeof fetch>()
  let closed = false

  beforeEach(() => {
    closed = false
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (path.startsWith('/api/v1/forecast?')) {
        const month = new URL(path, 'http://localhost').searchParams.get('from_month')!
        return jsonResponse({ months: [{ month, c_start: 200_000, r_start: 50_000, f_start: 150_000, income: 100_000, expense: 80_000, goal_allocations: 0, goal_releases: 0, goal_expenses: 0, goal_refunds: 0, adjustments: 0, c_end: 220_000, r_end: 50_000, f_end: 170_000, incomplete: false, closed }] })
      }
      if (init?.method === 'POST' && /\/api\/v1\/months\/\d{4}-\d{2}\/close$/.test(path)) {
        closed = true
        return jsonResponse({ month: path.split('/')[4], status: 'closed', version: 1 })
      }
      if (init?.method === 'POST' && /\/api\/v1\/months\/\d{4}-\d{2}\/reopen$/.test(path)) {
        closed = false
        return jsonResponse({ month: path.split('/')[4], status: 'open', version: 2 })
      }
      if (path === '/api/v1/accounts') return jsonResponse({ items: [], total: 0 })
      if (path === '/api/v1/goals') return jsonResponse({ items: [], total: 0 })
      if (path.startsWith('/api/v1/plan-items?')) return jsonResponse({ items: [], total: 0 })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('closes and reopens the currently selected month after confirmed server responses', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><DashboardPage /></QueryClientProvider>)

    const month = (await screen.findByLabelText('Выбранный месяц') as HTMLInputElement).value
    fireEvent.click(await screen.findByRole('button', { name: 'Закрыть месяц' }))

    expect(window.confirm).toHaveBeenCalledOnce()
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === `/api/v1/months/${month}/close` && init?.method === 'POST')).toBe(true))
    expect(await screen.findByText('Месяц закрыт')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Переоткрыть месяц' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === `/api/v1/months/${month}/reopen` && init?.method === 'POST')).toBe(true))
    expect(await screen.findByRole('button', { name: 'Закрыть месяц' })).toBeInTheDocument()
  })
})
