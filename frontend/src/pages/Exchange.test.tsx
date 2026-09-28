import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ExchangePage } from './Exchange'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
}

describe('exchange imports', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'POST' && path === '/api/v1/imports/project') return jsonResponse({ schema_version: 1, created: { accounts: 2, transactions: 3 } })
      if (init?.method === 'POST' && path === '/api/v1/imports/preview') return jsonResponse({ batch_id: 8, status: 'previewed', rows: [{ row: 2, normalized: {} }], errors: [] })
      if (init?.method === 'POST' && path === '/api/v1/imports/8/confirm') return jsonResponse({ batch_id: 8, created_count: 1 })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  function renderPage() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ExchangePage /></QueryClientProvider>)
  }

  it('uploads a canonical project ZIP to the dedicated atomic import endpoint', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Полный архив проекта' }))
    const archive = new File(['archive'], 'budget-project.zip', { type: 'application/zip' })
    fireEvent.change(screen.getByLabelText('Архив проекта ZIP'), { target: { files: [archive] } })
    fireEvent.click(screen.getByRole('button', { name: 'Импортировать полный проект' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/imports/project', expect.objectContaining({ method: 'POST' })))
    const [, request] = fetchMock.mock.calls.find(([url]) => url === '/api/v1/imports/project')!
    const uploaded = (request?.body as FormData).get('file') as File
    expect(uploaded.name).toBe('budget-project.zip')
    expect(await screen.findByText('Проект импортирован')).toBeInTheDocument()
    expect(screen.getByText(/Создано записей: 5/)).toBeInTheDocument()
  })

  it('explicitly opts in to creating categories and tags during CSV confirmation', async () => {
    renderPage()
    const csv = new File(['date,amount'], 'operations.csv', { type: 'text/csv' })
    fireEvent.change(screen.getByLabelText('Файл CSV'), { target: { files: [csv] } })
    fireEvent.click(screen.getByRole('button', { name: 'Проверить и показать предпросмотр' }))

    const allowReferences = await screen.findByRole('checkbox', { name: /Создать отсутствующие справочники/ })
    fireEvent.click(allowReferences)
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить импорт' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/imports/8/confirm')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url]) => url === '/api/v1/imports/8/confirm')!
    expect(JSON.parse(String(request?.body))).toEqual({ excluded_rows: [], create_references: true })
    expect(await screen.findByText('Импорт завершён')).toBeInTheDocument()
  })
})
