import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CalendarPage } from './Calendar'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
}

describe('calendar occurrence editing', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('moves and changes one recurring income, then restores the series', async () => {
    const fetchMock = vi.fn<typeof fetch>()
    let moved = false
    let version = 1
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'PUT' && path === '/api/v1/plan-items/12/overrides/2026-02') {
        const body = JSON.parse(String(init.body))
        moved = body.amount_minor !== null || body.moved_date !== null
        version += 1
        return jsonResponse({ plan_item_id: 12, month: '2026-02' })
      }
      if (path === '/api/v1/plan-items?month=2026-02') return jsonResponse({ items: moved ? [] : [{
        id: 12, title: 'Зарплата', kind: 'income', amount_minor: 100_000,
        base_amount_minor: 100_000, date: '2026-02-15', base_date: '2026-02-15',
        recurrence: 'monthly', occurrence_month: '2026-02', has_override: false, version,
      }], total: moved ? 0 : 1 })
      if (path === '/api/v1/plan-items?month=2026-03') return jsonResponse({ items: [
        ...(moved ? [{ id: 12, title: 'Зарплата', kind: 'income', amount_minor: 120_000, base_amount_minor: 100_000, date: '2026-03-05', base_date: '2026-02-15', recurrence: 'monthly', occurrence_month: '2026-02', has_override: true, version }] : []),
        { id: 12, title: 'Зарплата', kind: 'income', amount_minor: 100_000, base_amount_minor: 100_000, date: '2026-03-15', base_date: '2026-03-15', recurrence: 'monthly', occurrence_month: '2026-03', has_override: false, version },
      ], total: moved ? 2 : 1 })
      if (path.startsWith('/api/v1/plan-items?month=')) return jsonResponse({ items: [], total: 0 })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><CalendarPage /></QueryClientProvider>)

    fireEvent.change(screen.getByLabelText('Месяц календаря'), { target: { value: '2026-02' } })
    fireEvent.click(await screen.findByRole('button', { name: /Изменить Зарплата за феврал/ }))
    expect(screen.getByText(/Меняется только повторение за феврал/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Сумма'), { target: { value: '1 200' } })
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-03-05' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить дату' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/plan-items/12/overrides/2026-02' && init?.method === 'PUT')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/plan-items/12/overrides/2026-02' && init?.method === 'PUT')!
    expect(JSON.parse(String(request?.body))).toEqual({ amount_minor: 120_000, moved_date: '2026-03-05', cancelled: false, version: 1 })
    expect(screen.getByLabelText('Месяц календаря')).toHaveValue('2026-03')
    expect((await screen.findAllByRole('button', { name: /Изменить Зарплата за/ })).length).toBe(2)

    fireEvent.click(screen.getByRole('button', { name: /Изменить Зарплата за феврал/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Вернуть по серии' }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => url === '/api/v1/plan-items/12/overrides/2026-02' && init?.method === 'PUT')).toHaveLength(2))
    const resetRequest = fetchMock.mock.calls.filter(([url, init]) => url === '/api/v1/plan-items/12/overrides/2026-02' && init?.method === 'PUT')[1][1]
    expect(JSON.parse(String(resetRequest?.body))).toEqual({ amount_minor: null, moved_date: null, cancelled: false, version: 2 })
    expect(screen.getByLabelText('Месяц календаря')).toHaveValue('2026-02')
    expect(await screen.findByRole('button', { name: /Изменить Зарплата за феврал/ })).toBeInTheDocument()
  })

  it('assigns a precise date to a month-only payment', async () => {
    const fetchMock = vi.fn<typeof fetch>()
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'PUT' && path === '/api/v1/plan-items/21/overrides/2026-04') return jsonResponse({ id: 1 })
      if (path === '/api/v1/plan-items?month=2026-04') return jsonResponse({ items: [{
        id: 21, title: 'Коммунальные', kind: 'expense', amount_minor: 15_000,
        base_amount_minor: 15_000, date: null, base_date: null,
        occurrence_month: '2026-04', recurrence: 'none', has_override: false, version: 1,
      }], total: 1 })
      if (path.startsWith('/api/v1/plan-items?month=')) return jsonResponse({ items: [], total: 0 })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><CalendarPage /></QueryClientProvider>)

    fireEvent.change(screen.getByLabelText('Месяц календаря'), { target: { value: '2026-04' } })
    fireEvent.click(await screen.findByRole('button', { name: /Коммунальные/ }))
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-04-07' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить дату' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/plan-items/21/overrides/2026-04' && init?.method === 'PUT')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/plan-items/21/overrides/2026-04' && init?.method === 'PUT')!
    expect(JSON.parse(String(request?.body))).toEqual({ amount_minor: null, moved_date: '2026-04-07', cancelled: false, version: 1 })
  })
})
