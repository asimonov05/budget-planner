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
    fetchMock.mockClear()
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

  it('documents transfer CSV columns and previews amounts in both account currencies', async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'POST' && path === '/api/v1/imports/preview') return jsonResponse({
        batch_id: 9, status: 'previewed', errors: [], rows: [{ row: 2, normalized: {
          date: '2026-10-09', from_account: 'Основной', to_account: 'Доллары',
          from_currency: 'RUB', to_currency: 'USD', amount_minor: 800_000,
          to_amount_minor: 10_000, exchange_rate: '0.0125',
        } }],
      })
      if (init?.method === 'POST' && path === '/api/v1/imports/9/confirm') return jsonResponse({ batch_id: 9, created_count: 1 })
      throw new Error(`Unexpected request: ${path}`)
    })
    renderPage()
    fireEvent.change(screen.getByLabelText('Тип импорта'), { target: { value: 'transfers' } })
    const format = screen.getByRole('region', { name: 'Формат CSV: transfers' })
    expect(format).toHaveTextContent('from_account')
    expect(format).toHaveTextContent('to_account')
    expect(format).toHaveTextContent('exchange_rate')
    expect(screen.getByRole('link', { name: 'Скачать пример CSV' })).toHaveAttribute('download', 'transfers-template.csv')
    const csv = new File(['date;from_account;to_account;amount;exchange_rate\n2026-10-09;Основной;Доллары;8000;0,0125'], 'transfers.csv', { type: 'text/csv' })
    fireEvent.change(screen.getByLabelText('Файл CSV'), { target: { files: [csv] } })
    fireEvent.click(screen.getByRole('button', { name: 'Проверить и показать предпросмотр' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/imports/preview')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url]) => url === '/api/v1/imports/preview')!
    expect((request?.body as FormData).get('import_type')).toBe('transfers')
    expect(await screen.findByRole('region', { name: 'Проверенные строки CSV' })).toHaveTextContent(/8\s*000\s*₽.*100\s*\$/)
    expect(screen.queryByRole('checkbox', { name: /Создать отсутствующие справочники/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить импорт' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/imports/9/confirm')).toBe(true))
  })

  it('clears a previous preview when the CSV import type changes', async () => {
    renderPage()
    fireEvent.change(screen.getByLabelText('Файл CSV'), { target: { files: [new File(['date;amount;type;account'], 'operations.csv')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Проверить и показать предпросмотр' }))
    expect(await screen.findByText('Формат файла прошёл проверку')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Тип импорта'), { target: { value: 'transfers' } })
    expect(screen.getByText('Сначала загрузите файл')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Подтвердить импорт' })).not.toBeInTheDocument()
  })

  it('attaches the local bank PDF conversion skill to the CSV import page', () => {
    renderPage()
    expect(screen.getByText('Как подготовить PDF к импорту')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Скачать счета для ИИ' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Открыть скилл' })).toHaveAttribute('href', '/skills/bank-pdf-to-budget-csv/SKILL.md')
    expect(screen.getByRole('link', { name: 'Скачать SKILL.md' })).toHaveAttribute('download', 'bank-pdf-to-budget-csv-SKILL.md')
  })
})
