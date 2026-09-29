import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { PlanPage } from './Plan'

afterEach(() => {
  vi.unstubAllGlobals()
})

it('shows the estimated part of monthly category spending in the annual plan', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.startsWith('/api/v1/forecast?')) return new Response(JSON.stringify({ months: [{
      month: '2026-10', income: 100_000_00, expense: 30_000_00,
      estimated_expense_minor: 15_000_00, goal_allocations: 0,
      c_end: 70_000_00, r_end: 0, f_end: 70_000_00, incomplete: true,
      category_details: [{ category_id: 4, forecast_minor: 30_000_00, estimated_monthly_minor: 30_000_00, estimated_from_months: 3, estimated_added_minor: 15_000_00 }],
    }] }), { headers: { 'content-type': 'application/json' } })
    if (path === '/api/v1/categories?include_archived=true') return new Response(JSON.stringify({
      items: [{ id: 4, name: 'Продукты', kind: 'expense', monthly_estimate: true }], total: 1,
    }), { headers: { 'content-type': 'application/json' } })
    throw new Error(`Unexpected request: ${path}`)
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><PlanPage /></QueryClientProvider>)

  const category = await screen.findByText('Продукты · оценка')
  const estimate = screen.getByText('Примерные расходы')
  expect(category.closest('tr')).toHaveTextContent('30 000 ₽')
  expect(category.closest('tr')?.querySelector('button')).toHaveAttribute('title', expect.stringContaining('Среднее за 3 мес.'))
  expect(estimate.closest('tr')).toHaveTextContent('15 000 ₽')
  expect(screen.getByText('Свободно на конец').closest('tr')).toHaveTextContent('70 000 ₽')
})
