import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ThemeProvider } from '../lib/theme'
import { SettingsPage } from './Settings'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><ThemeProvider><SettingsPage /></ThemeProvider></QueryClientProvider>)
}

describe('settings directories', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => undefined })
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (path === '/api/v1/settings') return jsonResponse({ currency: 'RUB', timezone: 'Europe/Moscow', accounting_start_date: '2026-01-01', version: 1 })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({ items: [
        { id: 1, name: 'Карта', type: 'bank', initial_balance_minor: 0, initial_balance_date: '2026-01-01', current_balance_minor: 50_000, archived: false, version: 3 },
        { id: 2, name: 'Сбережения', type: 'savings', initial_balance_minor: 0, initial_balance_date: '2026-01-01', current_balance_minor: 100_000, archived: true, version: 4 },
      ], total: 2 })
      if (init?.method === 'PATCH' && path.startsWith('/api/v1/accounts/')) return jsonResponse({ id: Number(path.split('/').at(-1)), version: 4 })
      if (init?.method === 'DELETE' && path === '/api/v1/accounts/1?version=3') return new Response(null, { status: 204 })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('loads archived entries and reuses the directory form for a versioned edit', async () => {
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: /Счета/ }))

    await screen.findByText('Карта')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/accounts?include_archived=true', expect.objectContaining({ method: 'GET' }))
    expect(screen.getByText('Архив')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Изменить Карта' }))
    expect(screen.getByLabelText('Название')).toHaveValue('Карта')
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Основная карта' } })
    fireEvent.change(screen.getByLabelText('Тип счёта'), { target: { value: 'cash' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/accounts/1' && request?.method === 'PATCH')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, options]) => url === '/api/v1/accounts/1' && options?.method === 'PATCH')!
    expect(JSON.parse(String(request?.body))).toEqual({ name: 'Основная карта', type: 'cash', version: 3 })
  })

  it('switches between brightness modes, color schemes and fonts', () => {
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: /Оформление/ }))

    expect(screen.getByRole('radio', { name: /Светлая/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Тёмная/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Системная/ })).toBeChecked()

    fireEvent.click(screen.getByRole('radio', { name: /Тёмная/ }))
    expect(screen.getByRole('radio', { name: /Тёмная/ })).toBeChecked()
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')

    expect(screen.getByRole('radio', { name: /Лес/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: /Океан/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Слива/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Янтарь/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: /Слива/ }))
    expect(screen.getByRole('radio', { name: /Слива/ })).toBeChecked()
    expect(document.documentElement).toHaveAttribute('data-color-scheme', 'plum')

    expect(screen.getByRole('radio', { name: /Классический/ })).toBeChecked()
    fireEvent.click(screen.getByRole('radio', { name: /Golos Text/ }))
    expect(screen.getByRole('radio', { name: /Golos Text/ })).toBeChecked()
    expect(document.documentElement).toHaveAttribute('data-font', 'golos')
  })

  it('marks an expense category for monthly estimates', async () => {
    fetchMock.mockClear()
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (path === '/api/v1/settings') return jsonResponse({ currency: 'RUB', timezone: 'Europe/Moscow', accounting_start_date: '2026-01-01', version: 1 })
      if (path === '/api/v1/categories?include_archived=true') return jsonResponse({ items: [{ id: 4, name: 'Продукты', kind: 'expense', color: '#557a5d', monthly_estimate: false, archived: false, version: 1 }], total: 1 })
      if (path === '/api/v1/categories/4' && init?.method === 'PATCH') return jsonResponse({ id: 4, name: 'Продукты', monthly_estimate: true, version: 2 })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: /Категории/ }))
    await screen.findByText('Продукты')
    fireEvent.click(screen.getByRole('button', { name: 'Изменить Продукты' }))
    const toggle = screen.getByRole('checkbox', { name: /Оценивать расход каждый месяц/ })
    expect(toggle).not.toBeChecked()
    fireEvent.click(toggle)
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/categories/4' && request?.method === 'PATCH')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, options]) => url === '/api/v1/categories/4' && options?.method === 'PATCH')!
    expect(JSON.parse(String(request?.body))).toEqual(expect.objectContaining({ monthly_estimate: true, version: 1 }))
  })

  it('archives, restores and hard-deletes with the current version', async () => {
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: /Счета/ }))
    await screen.findByText('Карта')

    fireEvent.click(screen.getByRole('button', { name: 'Архивировать Карта' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/accounts/1' && request?.method === 'PATCH' && JSON.parse(String(request.body)).archived === true)).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Восстановить Сбережения' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/accounts/2' && request?.method === 'PATCH' && JSON.parse(String(request.body)).archived === false)).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Удалить Карта' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/accounts/1?version=3' && request?.method === 'DELETE')).toBe(true))
    expect(window.confirm).toHaveBeenCalled()
  })

  it('keeps a protected entry visible and explains a delete conflict', async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (path === '/api/v1/settings') return jsonResponse({ currency: 'RUB', timezone: 'Europe/Moscow', accounting_start_date: '2026-01-01', version: 1 })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({ items: [{ id: 1, name: 'Карта', type: 'bank', current_balance_minor: 0, archived: false, version: 3 }], total: 1 })
      if (init?.method === 'DELETE' && path === '/api/v1/accounts/1?version=3') return jsonResponse({ code: 'http_error', message: 'Счёт используется в истории; архивируйте его', field_errors: [], request_id: 'test' }, 409)
      throw new Error(`Unexpected request: ${path}`)
    })
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: /Счета/ }))
    await screen.findByText('Карта')
    fireEvent.click(screen.getByRole('button', { name: 'Удалить Карта' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Счёт используется в истории; архивируйте его')
    expect(screen.getByText('Карта')).toBeInTheDocument()
  })

  it('creates a gross salary rule for a separate employer', async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (path === '/api/v1/settings') return jsonResponse({ currency: 'RUB', timezone: 'Europe/Moscow', accounting_start_date: '2026-01-01', salary_enabled: true, version: 2 })
      if (path === '/api/v1/salary-rules?include_archived=true') return jsonResponse({ items: [], total: 0 })
      if (path.startsWith('/api/v1/salary-payments?')) return jsonResponse({ items: [], total: 0 })
      if (path.startsWith('/api/v1/transactions?')) return jsonResponse({ items: [], total: 0 })
      if (path === '/api/v1/accounts') return jsonResponse({ items: [{ id: 1, name: 'Карта' }] })
      if (path === '/api/v1/categories?kind=income') return jsonResponse({ items: [] })
      if (path === '/api/v1/salary-rules' && init?.method === 'POST') return jsonResponse({ id: 1 }, 201)
      throw new Error(`Unexpected request: ${path}`)
    })
    renderSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Зарплата' }))
    await screen.findByText('Зарплатные правила')
    fireEvent.click(screen.getByRole('button', { name: 'Добавить' }))
    await screen.findByRole('option', { name: 'Карта' })
    fireEvent.change(screen.getByLabelText('Работодатель'), { target: { value: 'Работодатель А' } })
    fireEvent.change(screen.getByLabelText('Зарплата за месяц до налога'), { target: { value: '100000' } })
    fireEvent.change(screen.getByLabelText('Счёт поступления'), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/salary-rules' && request?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, options]) => url === '/api/v1/salary-rules' && options?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual(expect.objectContaining({ name: 'Работодатель А', gross_minor: 10_000_000, advance_share_bps: 4_000, account_id: 1 }))
  })
})
