import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { menuStorageKey } from '../lib/menuPreferences'
import { Layout } from './Layout'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
}

function renderLayout() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Routes><Route element={<Layout/>}>
          <Route index element={<div>Обзор бюджета</div>}/>
          <Route path="notifications" element={<div>Входящие уведомления</div>}/>
        </Route></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function menuLabels() {
  return within(screen.getByRole('navigation', { name: 'Основное меню' }))
    .getAllByRole('link').map((link) => link.getAttribute('aria-label'))
}

const stored = new Map<string, string>()
const memoryStorage: Storage = {
  get length() { return stored.size },
  clear: () => stored.clear(),
  getItem: (key) => stored.get(key) ?? null,
  key: (index) => [...stored.keys()][index] ?? null,
  removeItem: (key) => { stored.delete(key) },
  setItem: (key, value) => { stored.set(key, value) },
}
const sessionStored = new Map<string, string>()
const memorySessionStorage: Storage = {
  get length() { return sessionStored.size },
  clear: () => sessionStored.clear(),
  getItem: (key) => sessionStored.get(key) ?? null,
  key: (index) => [...sessionStored.keys()][index] ?? null,
  removeItem: (key) => { sessionStored.delete(key) },
  setItem: (key, value) => { sessionStored.set(key, value) },
}

describe('sidebar menu preferences', () => {
  const fetchMock = vi.fn<typeof fetch>()
  let userId = 7
  let previewNotification: unknown = null

  beforeEach(() => {
    userId = 7
    previewNotification = null
    memoryStorage.clear()
    memorySessionStorage.clear()
    vi.stubGlobal('localStorage', memoryStorage)
    vi.stubGlobal('sessionStorage', memorySessionStorage)
    fetchMock.mockImplementation(async (input) => {
      const path = String(input)
      if (path === '/api/v1/auth/me') return jsonResponse({ id: userId, username: `user${userId}` })
      if (path === '/api/v1/notifications/unread-count') return jsonResponse({ count: 0 })
      if (path === '/api/v1/notifications/release-preview') return jsonResponse(previewNotification)
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reorders and hides entries, then restores them for the same user only', async () => {
    const view = renderLayout()
    const configure = await screen.findByRole('button', { name: 'Настроить меню' })
    await waitFor(() => expect(configure).toBeEnabled())

    fireEvent.click(configure)
    fireEvent.click(screen.getByRole('button', { name: 'Поднять Доходы' }))
    const dragged = new Map<string, string>()
    const dataTransfer = {
      effectAllowed: 'move',
      dropEffect: 'move',
      setData: (type: string, value: string) => { dragged.set(type, value) },
      getData: (type: string) => dragged.get(type) ?? '',
      setDragImage: vi.fn(),
    }
    const goalsHandle = screen.getByRole('button', { name: 'Перетащить Цели' })
    const goalsRow = goalsHandle.closest('.menu-editor-row')
    const accountsRow = screen.getByRole('button', { name: 'Перетащить Счета' }).closest('.menu-editor-row')!
    fireEvent.dragStart(goalsHandle, { dataTransfer })
    expect(dataTransfer.setDragImage).toHaveBeenCalledWith(goalsRow, expect.any(Number), expect.any(Number))
    fireEvent.dragOver(accountsRow, { dataTransfer })
    expect(accountsRow).toHaveClass('is-drop-before')
    fireEvent.drop(accountsRow, { dataTransfer })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Показывать Уведомления' }))
    expect(menuLabels().indexOf('Доходы')).toBeLessThan(menuLabels().indexOf('Календарь'))
    expect(menuLabels().indexOf('Цели')).toBeLessThan(menuLabels().indexOf('Счета'))
    expect(menuLabels()).not.toContain('Уведомления')
    expect(JSON.parse(window.localStorage.getItem(menuStorageKey('id-7'))!)).toEqual(expect.objectContaining({
      hidden: ['/notifications'],
    }))

    view.unmount()
    const sameUser = renderLayout()
    await waitFor(() => expect(menuLabels().indexOf('Доходы')).toBeLessThan(menuLabels().indexOf('Календарь')))
    expect(menuLabels()).not.toContain('Уведомления')
    sameUser.unmount()

    userId = 8
    // A new user gets the default menu, even in the same browser.
    window.localStorage.setItem(menuStorageKey('id-8'), JSON.stringify({ order: ['/'], hidden: [] }))
    renderLayout()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Настроить меню' })).toBeEnabled())
    await waitFor(() => expect(menuLabels().length).toBe(13))
    expect(menuLabels()).toContain('Уведомления')
  })

  it('keeps menu settings reachable when entries are hidden and can reset the defaults', async () => {
    renderLayout()
    const configure = await screen.findByRole('button', { name: 'Настроить меню' })
    await waitFor(() => expect(configure).toBeEnabled())

    fireEvent.click(configure)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Показывать Настройки' }))
    expect(menuLabels()).not.toContain('Настройки')
    expect(configure).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Сбросить меню' }))
    expect(menuLabels()).toContain('Настройки')
    expect(menuLabels().slice(0, 3)).toEqual(['Обзор', 'Счета', 'План'])
  })

  it('shows a release preview even when notifications are hidden and opens the inbox once', async () => {
    previewNotification = {
      id: 45, kind: 'release', title: 'Версия 0.2', body: 'Коротко о новых возможностях',
      release_note_id: 9, created_at: '2026-10-04T12:00:00Z', read_at: null,
    }
    memoryStorage.setItem(menuStorageKey('id-7'), JSON.stringify({ order: ['/'], hidden: ['/notifications'] }))
    const view = renderLayout()

    const open = await screen.findByRole('button', { name: 'Открыть уведомления: Версия 0.2' })
    expect(menuLabels()).not.toContain('Уведомления')
    expect(screen.getByText('Коротко о новых возможностях')).toBeInTheDocument()
    fireEvent.click(open)

    expect(await screen.findByText('Входящие уведомления')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Открыть уведомления: Версия 0.2' })).not.toBeInTheDocument()
    expect(memorySessionStorage.getItem('budget-planner-release-preview-seen:id-7:45')).toBe('1')
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/read'))).toBe(false)

    view.unmount()
    renderLayout()
    await screen.findByText('Обзор бюджета')
    expect(screen.queryByRole('button', { name: 'Открыть уведомления: Версия 0.2' })).not.toBeInTheDocument()
  })
})
