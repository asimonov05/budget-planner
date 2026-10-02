import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationsPage } from './Notifications'

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
    fireEvent.click(screen.getByRole('button', { name: 'Прочитано' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Прочитано' })).not.toBeInTheDocument())
    expect(screen.getByText('Прочитано')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/notifications/7/read', expect.objectContaining({ method: 'POST' }))
  })

  it('lets the owner save a release note draft', async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (path === '/api/v1/notifications?limit=50&offset=0') return response({ items: [], total: 0, unread: 0 })
      if (path === '/api/v1/users') return response({ items: [{ id: 1, username: 'owner', active: true }], total: 1 })
      if (path === '/api/v1/release-notes/manage') return response([])
      if (path === '/api/v1/release-notes' && init?.method === 'POST') return response({ id: 3, release_version: '1.4.0', title: 'Новые отчёты', body: 'Добавили отчёты', status: 'draft', created_at: '2026-10-02T12:00:00Z', updated_at: '2026-10-02T12:00:00Z', published_at: null })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage(true)
    fireEvent.click(screen.getByRole('tab', { name: 'Публикация' }))
    fireEvent.change(screen.getByLabelText('Версия'), { target: { value: '1.4.0' } })
    fireEvent.change(screen.getAllByLabelText('Заголовок')[1], { target: { value: 'Новые отчёты' } })
    fireEvent.change(screen.getByLabelText('Что изменилось'), { target: { value: 'Добавили отчёты' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }))
    await waitFor(() => expect(screen.getByText('Черновик сохранён')).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/release-notes', expect.objectContaining({ method: 'POST', body: JSON.stringify({ release_version: '1.4.0', title: 'Новые отчёты', body: 'Добавили отчёты' }) }))
  })
})
