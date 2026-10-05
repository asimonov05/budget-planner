import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationsPage, ReleaseNotePage } from './Notifications'

function response(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
}

function renderPage(admin: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } })
  client.setQueryData(['me'], { id: admin ? 1 : 2, username: admin ? 'owner' : 'alice', is_admin: admin })
  render(<QueryClientProvider client={client}><MemoryRouter><NotificationsPage /></MemoryRouter></QueryClientProvider>)
}

describe('notifications page', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock) })
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('shows an inbox item and marks it read', async () => {
    let read = false
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (path === '/api/v1/notifications/7/read' && init?.method === 'POST') {
        read = true
        return response({ id: 7, kind: 'message', title: 'Для вас', body: 'Важная новость', created_at: '2026-10-02T12:00:00Z', read_at: '2026-10-02T12:01:00Z', release_note_id: null })
      }
      if (path === '/api/v1/notifications?limit=50&offset=0') return response({ items: [{ id: 7, kind: 'message', title: 'Для вас', body: 'Важная новость', created_at: '2026-10-02T12:00:00Z', read_at: read ? '2026-10-02T12:01:00Z' : null, release_note_id: null }], total: 1, unread: read ? 0 : 1 })
      if (path === '/api/v1/notifications/unread-count') return response({ count: read ? 0 : 1 })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(false)
    expect(await screen.findByText('Важная новость')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Публикация' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Отметить прочитанным' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Отметить прочитанным' })).not.toBeInTheDocument())
    expect(screen.getByText('Всё прочитано')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/notifications/7/read', expect.objectContaining({ method: 'POST' }))
  })

  it('marks all notifications read and links a release to its full page', async () => {
    let readAll = false
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (path === '/api/v1/notifications/read-all' && init?.method === 'POST') {
        readAll = true
        return response({ updated: 2 })
      }
      if (path === '/api/v1/notifications?limit=50&offset=0') return response({ items: [
        { id: 8, kind: 'release', title: 'Версия 1.4', body: 'Кратко о новых отчётах', created_at: '2026-10-02T12:00:00Z', read_at: readAll ? '2026-10-02T12:01:00Z' : null, release_note_id: 3 },
        { id: 7, kind: 'message', title: 'Для вас', body: 'Новость', created_at: '2026-10-01T12:00:00Z', read_at: readAll ? '2026-10-02T12:01:00Z' : null, release_note_id: null },
      ], total: 2, unread: readAll ? 0 : 2 })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(false)
    expect(await screen.findByText('Кратко о новых отчётах')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'О релизе' })).toHaveAttribute('href', '/release-notes/3')
    fireEvent.click(screen.getByRole('button', { name: 'Прочитать все' }))
    await waitFor(() => expect(screen.getByText('Всё прочитано')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Прочитать все' })).toBeDisabled()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/notifications/read-all', expect.objectContaining({ method: 'POST' }))
  })

  it('renders the full release note on a separate route', async () => {
    fetchMock.mockImplementation(async (input) => {
      if (String(input) === '/api/v1/release-notes/3') return response({ id: 3, release_version: '1.4.0', title: 'Новые отчёты', summary: 'Краткий анонс', body: '# Что нового\n- Первый отчёт\n- Второй отчёт', status: 'published', created_at: '2026-10-02T12:00:00Z', updated_at: '2026-10-02T12:00:00Z', published_at: '2026-10-02T12:00:00Z' })
      throw new Error(`Unexpected request: ${String(input)}`)
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/release-notes/3']}><Routes><Route path="/release-notes/:id" element={<ReleaseNotePage />} /></Routes></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByRole('heading', { name: 'Новые отчёты' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Что нового' })).toBeInTheDocument()
    expect(screen.getByText('Первый отчёт')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'К истории версий' })).toHaveAttribute('href', '/notifications?tab=releases')
  })

  it('lets the owner save a release note draft', async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (path === '/api/v1/notifications?limit=50&offset=0') return response({ items: [], total: 0, unread: 0 })
      if (path === '/api/v1/users') return response({ items: [{ id: 1, username: 'owner', active: true }], total: 1 })
      if (path === '/api/v1/release-notes/manage') return response([])
      if (path === '/api/v1/release-notes' && init?.method === 'POST') return response({ id: 3, release_version: '1.4.0', title: 'Новые отчёты', summary: 'Удобнее смотреть бюджет', body: 'Добавили отчёты', status: 'draft', created_at: '2026-10-02T12:00:00Z', updated_at: '2026-10-02T12:00:00Z', published_at: null })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(true)
    fireEvent.click(screen.getByRole('tab', { name: 'Публикация' }))
    fireEvent.change(screen.getByLabelText('Версия'), { target: { value: '1.4.0' } })
    fireEvent.change(screen.getAllByLabelText('Заголовок')[1], { target: { value: 'Новые отчёты' } })
    fireEvent.change(screen.getByLabelText('Краткий анонс'), { target: { value: 'Удобнее смотреть бюджет' } })
    fireEvent.change(screen.getByLabelText('Полное описание'), { target: { value: 'Добавили отчёты' } })
    fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр страницы' }))
    expect(screen.getByRole('region', { name: 'Предпросмотр страницы релиза' })).toHaveTextContent('Удобнее смотреть бюджет')
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }))
    await waitFor(() => expect(screen.getByText('Черновик сохранён')).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/release-notes', expect.objectContaining({ method: 'POST', body: JSON.stringify({ release_version: '1.4.0', title: 'Новые отчёты', summary: 'Удобнее смотреть бюджет', body: 'Добавили отчёты' }) }))
  })
})
