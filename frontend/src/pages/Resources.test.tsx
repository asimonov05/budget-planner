import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ResourcePage } from './Resources'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
}

describe('transaction resource integration', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    fetchMock.mockClear()
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'POST' && path === '/api/v1/transactions') return jsonResponse({ id: 9 })
      if (init?.method === 'POST' && path === '/api/v1/transfers') return jsonResponse({ id: 10 })
      if (init?.method === 'PATCH' && path === '/api/v1/transfers/8') return jsonResponse({ id: 8, version: 2 })
      if (init?.method === 'DELETE' && path === '/api/v1/transfers/8?version=1') return new Response(null, { status: 204 })
      if (path.startsWith('/api/v1/transactions?')) return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 })
      if (path === '/api/v1/transfers') return jsonResponse({ items: [{ id: 8, from_account_id: 3, to_account_id: 5, amount_minor: 75_000, date: '2026-09-20', comment: 'В резерв', version: 1 }], total: 1 })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({ items: [{ id: 3, name: 'Карта', current_balance_minor: 100_000, version: 1 }, { id: 5, name: 'Накопительный', current_balance_minor: 50_000, version: 1 }], total: 2 })
      if (path === '/api/v1/categories?include_archived=true') return jsonResponse({ items: [{ id: 4, name: 'Продукты', kind: 'expense', archived: false, version: 1 }], total: 1 })
      if (path === '/api/v1/tags?include_archived=true') return jsonResponse({ items: [{ id: 6, name: 'Семья', archived: false, version: 1 }], total: 1 })
      if (path === '/api/v1/loans?include_archived=true') return jsonResponse({ items: [{ id: 7, name: 'Ипотека', schedule_mode: 'auto', archived: false }], total: 1 })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('validates required API fields and sends numeric relation ids', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="transaction" /></QueryClientProvider>)

    await screen.findByText('Операций пока нет')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/transactions?limit=100&offset=0', expect.objectContaining({ method: 'GET' }))
    fireEvent.click(screen.getByRole('button', { name: 'Добавить операцию' }))
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    expect(await screen.findByText('Укажите сумму больше нуля')).toBeInTheDocument()
    expect(screen.getByText('Укажите дату')).toBeInTheDocument()
    expect(screen.getByText('Выберите счёт')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/transactions' && init?.method === 'POST')).toBe(false)

    fireEvent.change(screen.getByLabelText(/^Название/), { target: { value: 'Обед' } })
    fireEvent.change(screen.getByLabelText(/^Сумма/), { target: { value: '1 250,50' } })
    fireEvent.change(screen.getByLabelText(/^Дата/), { target: { value: '2026-09-21' } })
    fireEvent.change(screen.getByLabelText(/^Счёт/), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText(/^Категория/), { target: { value: '4' } })
    const tags = screen.getByLabelText('Теги') as HTMLSelectElement
    tags.options[0].selected = true
    fireEvent.change(tags)
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/transactions' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/transactions' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual({
      type: 'expense', amount_minor: 125050, date: '2026-09-21', account_id: 3,
      category_id: 4, description: 'Обед', comment: null, tag_ids: [6],
      merchant_currency: null, merchant_amount_minor: null, merchant_exchange_rate: null,
    })
    expect(new Headers(request?.headers).get('Idempotency-Key')).toMatch(/^transaction-/)
  })

  it('links a new actual loan payment with the early repayment strategy', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="transaction" /></QueryClientProvider>)

    await screen.findByText('Операций пока нет')
    fireEvent.click(screen.getByRole('button', { name: 'Добавить операцию' }))
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Досрочное погашение' } })
    fireEvent.change(screen.getByLabelText(/^(Сумма|Списать)/), { target: { value: '10 000' } })
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-09-21' } })
    fireEvent.change(screen.getByLabelText('Счёт'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Кредит'), { target: { value: '7' } })
    fireEvent.change(screen.getByLabelText('Досрочное погашение'), { target: { value: 'reduce_term' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/transactions' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/transactions' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual(expect.objectContaining({
      loan_id: 7, prepayment_strategy: 'reduce_term', amount_minor: 1_000_000,
    }))
  })

  it('links an existing expense to a loan without changing the stated debt', async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'POST' && path === '/api/v1/loans/7/transactions/15/link') return jsonResponse({ loan_id: 7, transaction_id: 15 })
      if (path.startsWith('/api/v1/transactions?')) return jsonResponse({ items: [{ id: 15, type: 'expense', description: 'Старый платёж', amount_minor: 10_000, date: '2026-02-01', account_id: 3, version: 1 }], total: 1 })
      if (path === '/api/v1/loans?include_archived=true') return jsonResponse({ items: [{ id: 7, name: 'Ипотека', schedule_mode: 'auto', archived: false }], total: 1 })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({ items: [{ id: 3, name: 'Карта', archived: false }], total: 1 })
      if (path === '/api/v1/categories?include_archived=true' || path === '/api/v1/tags?include_archived=true' || path === '/api/v1/transfers') return jsonResponse({ items: [], total: 0 })
      throw new Error(`Unexpected request: ${path}`)
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="transaction" /></QueryClientProvider>)

    await screen.findByText('Старый платёж')
    fireEvent.click(screen.getByRole('button', { name: 'Связать с кредитом Старый платёж' }))
    fireEvent.change(screen.getByLabelText('Кредит'), { target: { value: '7' } })
    fireEvent.change(screen.getByLabelText('В основной долг'), { target: { value: '80' } })
    fireEvent.change(screen.getByLabelText('В проценты'), { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: 'Связать' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/loans/7/transactions/15/link' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/loans/7/transactions/15/link' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual({ principal_minor: 8_000, interest_minor: 2_000, already_reflected_in_balance: true, prepayment_strategy: null })
    expect(new Headers(request?.headers).get('Idempotency-Key')).toMatch(/^loan-link-/)
  })

  it('can remove a historical link that did not change the debt balance', async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'DELETE' && path === '/api/v1/loans/7/transactions/15/link?version=2') return new Response(null, { status: 204 })
      if (path.startsWith('/api/v1/transactions?')) return jsonResponse({ items: [{ id: 15, type: 'expense', description: 'Старый платёж', amount_minor: 10_000, date: '2026-02-01', account_id: 3, loan_id: 7, loan_balance_applied: false, version: 2 }], total: 1 })
      if (path === '/api/v1/loans?include_archived=true') return jsonResponse({ items: [{ id: 7, name: 'Ипотека', schedule_mode: 'auto', archived: false }], total: 1 })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({ items: [{ id: 3, name: 'Карта', archived: false }], total: 1 })
      if (path === '/api/v1/categories?include_archived=true' || path === '/api/v1/tags?include_archived=true' || path === '/api/v1/transfers') return jsonResponse({ items: [], total: 0 })
      throw new Error(`Unexpected request: ${path}`)
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="transaction" /></QueryClientProvider>)

    await screen.findByText('Старый платёж')
    fireEvent.click(screen.getByRole('button', { name: 'Отвязать от кредита Старый платёж' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/loans/7/transactions/15/link?version=2' && init?.method === 'DELETE')).toBe(true))
  })

  it('shows transfer history with resolved account names', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="transaction" /></QueryClientProvider>)

    expect(await screen.findByText('Карта → Накопительный')).toBeInTheDocument()
    expect(screen.getByText('Перевод')).toBeInTheDocument()
    expect(screen.getByText(/750\s*₽ → 750\s*₽/)).toBeInTheDocument()
  })

  it('creates an atomic internal transfer with distinct source and destination accounts', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="transaction" /></QueryClientProvider>)

    await screen.findByText('Операций пока нет')
    fireEvent.click(screen.getByRole('button', { name: 'Перевод между счетами' }))
    expect(screen.getByLabelText('Тип операции')).toHaveValue('transfer')
    fireEvent.change(screen.getByLabelText(/^(Сумма|Списать)/), { target: { value: '10 000' } })
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-09-22' } })
    fireEvent.change(screen.getByLabelText('Со счёта'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('На счёт'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('Комментарий'), { target: { value: 'В резерв' } })
    fireEvent.click(screen.getByRole('button', { name: 'Перевести' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/transfers' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/transfers' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual({
      from_account_id: 3,
      to_account_id: 5,
      amount_minor: 1_000_000,
      exchange_rate: null,
      date: '2026-09-22',
      comment: 'В резерв',
    })
    expect(new Headers(request?.headers).get('Idempotency-Key')).toMatch(/^transaction-/)
    expect(await screen.findByText('Перевод сохранён')).toBeInTheDocument()
  })

  it('edits and deletes a transfer with optimistic version checks', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="transaction" /></QueryClientProvider>)

    await screen.findByText('Карта → Накопительный')
    fireEvent.click(screen.getByRole('button', { name: 'Изменить перевод 8' }))
    expect(screen.getByLabelText(/^(Сумма|Списать)/)).toHaveValue('750,00')
    fireEvent.change(screen.getByLabelText(/^(Сумма|Списать)/), { target: { value: '1 000' } })
    fireEvent.change(screen.getByLabelText('Комментарий'), { target: { value: 'Новый резерв' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/transfers/8' && request?.method === 'PATCH')).toBe(true))
    const [, patchRequest] = fetchMock.mock.calls.find(([url, request]) => url === '/api/v1/transfers/8' && request?.method === 'PATCH')!
    expect(JSON.parse(String(patchRequest?.body))).toEqual({ from_account_id: 3, to_account_id: 5, amount_minor: 100_000, exchange_rate: null, date: '2026-09-20', comment: 'Новый резерв', version: 1 })

    fireEvent.click(await screen.findByRole('button', { name: 'Удалить перевод 8' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/transfers/8?version=1' && request?.method === 'DELETE')).toBe(true))
  })

  it('uses the entered rate for a cross-currency transfer and shows both account changes', async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'POST' && path === '/api/v1/transfers') return jsonResponse({ id: 10 })
      if (path.startsWith('/api/v1/transactions?')) return jsonResponse({ items: [], total: 0 })
      if (path === '/api/v1/transfers' || path.includes('/categories?') || path.includes('/tags?') || path.includes('/loans?')) return jsonResponse({ items: [], total: 0 })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({ items: [
        { id: 3, name: 'Рубли', currency: 'RUB', archived: false },
        { id: 5, name: 'Доллары', currency: 'USD', archived: false },
      ], total: 2 })
      if (path.startsWith('/api/v1/currencies/quote?')) return jsonResponse({ from_currency: 'RUB', to_currency: 'USD', rate: '0.012', requested_date: '2026-09-22', effective_date: '2026-09-22', source: 'CBR', indicative: true })
      throw new Error(`Unexpected request: ${path}`)
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="transaction" /></QueryClientProvider>)
    await screen.findByText('Операций пока нет')
    fireEvent.click(screen.getByRole('button', { name: 'Перевод между счетами' }))
    fireEvent.change(screen.getByLabelText('Списать, RUB'), { target: { value: '10 000' } })
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-09-22' } })
    fireEvent.change(screen.getByLabelText('Со счёта'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('На счёт'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('Курс: 1 RUB в USD'), { target: { value: '0,011' } })
    expect(screen.getByText(/На счёт: \+110\s*\$/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Перевести' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/transfers' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/transfers' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual(expect.objectContaining({ amount_minor: 1_000_000, exchange_rate: '0.011' }))
  })

  it('shows a foreign-currency purchase above the account-currency debit', async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'POST' && path === '/api/v1/transactions') return jsonResponse({ id: 9 })
      if (path.startsWith('/api/v1/transactions?')) return jsonResponse({ items: [], total: 0 })
      if (path === '/api/v1/transfers' || path.includes('/categories?') || path.includes('/tags?') || path.includes('/loans?')) return jsonResponse({ items: [], total: 0 })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({ items: [{ id: 3, name: 'Рублёвая карта', currency: 'RUB', archived: false }], total: 1 })
      if (path === '/api/v1/currencies') return jsonResponse({ items: [
        { code: 'RUB', name: 'Российский рубль', minor_digits: 2, popular: true },
        { code: 'EUR', name: 'Евро', minor_digits: 2, popular: true },
      ] })
      if (path.startsWith('/api/v1/currencies/quote?')) return jsonResponse({ from_currency: 'EUR', to_currency: 'RUB', rate: '90', requested_date: '2026-09-22', effective_date: '2026-09-22', source: 'CBR', indicative: true })
      throw new Error(`Unexpected request: ${path}`)
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="transaction" /></QueryClientProvider>)
    await screen.findByText('Операций пока нет')
    fireEvent.click(screen.getByRole('button', { name: 'Добавить операцию' }))
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Билет' } })
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-09-22' } })
    fireEvent.change(screen.getByLabelText('Счёт'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Валюта оплаты'), { target: { value: 'EUR' } })
    fireEvent.change(screen.getByLabelText('Сумма оплаты, EUR'), { target: { value: '20' } })
    fireEvent.change(screen.getByLabelText('Курс: 1 EUR в RUB'), { target: { value: '96,5' } })
    expect(screen.getByText(/Со счёта спишется: −1\s*930\s*₽/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/transactions' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/transactions' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual(expect.objectContaining({
      amount_minor: 193_000, merchant_currency: 'EUR', merchant_amount_minor: 2_000, merchant_exchange_rate: '96.5',
    }))
  })
})

describe('archived directory references in resource forms', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    fetchMock.mockClear()
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'PATCH' && path === '/api/v1/transactions/41') return jsonResponse({ id: 41, version: 3 })
      if (init?.method === 'PATCH' && path === '/api/v1/transfers/18') return jsonResponse({ id: 18, version: 2 })
      if (path.startsWith('/api/v1/transactions?')) return jsonResponse({
        items: [{
          id: 41, type: 'expense', amount_minor: 12_300, date: '2026-09-19', account_id: 13,
          category_id: 14, description: 'Архивные связи', tags: [{ id: 16, name: 'Старый тег', archived: true }],
          comment: 'Историческая запись', version: 2,
        }],
        total: 1, limit: 100, offset: 0,
      })
      if (path === '/api/v1/transfers') return jsonResponse({
        items: [{ id: 18, from_account_id: 13, to_account_id: 15, amount_minor: 25_000, date: '2026-09-18', version: 1 }],
        total: 1,
      })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({
        items: [
          { id: 3, name: 'Активная карта', archived: false, version: 1 },
          { id: 13, name: 'Старая карта', archived: true, version: 2 },
          { id: 15, name: 'Старый вклад', archived: true, version: 2 },
        ],
        total: 3,
      })
      if (path === '/api/v1/categories?include_archived=true') return jsonResponse({
        items: [
          { id: 4, name: 'Активная категория', kind: 'expense', archived: false, version: 1 },
          { id: 14, name: 'Старая категория', kind: 'expense', archived: true, version: 2 },
        ],
        total: 2,
      })
      if (path === '/api/v1/tags?include_archived=true') return jsonResponse({
        items: [
          { id: 6, name: 'Активный тег', archived: false, version: 1 },
          { id: 16, name: 'Старый тег', archived: true, version: 2 },
        ],
        total: 2,
      })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('keeps current archived account, category and tags while excluding them from new records', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="transaction" /></QueryClientProvider>)

    await screen.findByText('Архивные связи')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/accounts?include_archived=true', expect.objectContaining({ method: 'GET' }))
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/categories?include_archived=true', expect.objectContaining({ method: 'GET' }))
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tags?include_archived=true', expect.objectContaining({ method: 'GET' }))

    fireEvent.click(screen.getByRole('button', { name: 'Изменить Архивные связи' }))
    const editAccount = screen.getAllByRole('combobox').find((element) => (element as HTMLSelectElement).value === '13')
    expect(editAccount).toHaveValue('13')
    expect(screen.getByRole('option', { name: 'Старая карта · RUB (в архиве)' })).toBeInTheDocument()
    expect(screen.getByLabelText('Категория')).toHaveValue('14')
    expect(screen.getByRole('option', { name: 'Старая категория (в архиве)' })).toBeInTheDocument()
    const editTags = screen.getByLabelText('Теги') as HTMLSelectElement
    expect(Array.from(editTags.selectedOptions).map((option) => option.value)).toEqual(['16'])
    expect(screen.getByRole('option', { name: 'Старый тег (в архиве)' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/transactions/41' && request?.method === 'PATCH')).toBe(true))
    const [, transactionRequest] = fetchMock.mock.calls.find(([url, request]) => url === '/api/v1/transactions/41' && request?.method === 'PATCH')!
    expect(JSON.parse(String(transactionRequest?.body))).toEqual(expect.objectContaining({ category_id: 14, tag_ids: [16], version: 2 }))

    fireEvent.click(await screen.findByRole('button', { name: 'Изменить перевод 18' }))
    expect(screen.getByLabelText('Со счёта')).toHaveValue('13')
    expect(screen.getByLabelText('На счёт')).toHaveValue('15')
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/transfers/18' && request?.method === 'PATCH')).toBe(true))
    const [, transferRequest] = fetchMock.mock.calls.find(([url, request]) => url === '/api/v1/transfers/18' && request?.method === 'PATCH')!
    expect(JSON.parse(String(transferRequest?.body))).toEqual(expect.objectContaining({ from_account_id: 13, to_account_id: 15, version: 1 }))

    fireEvent.click(await screen.findByRole('button', { name: 'Добавить операцию' }))
    const newAccount = screen.getByLabelText(/^Счёт/) as HTMLSelectElement
    const newCategory = screen.getByLabelText('Категория') as HTMLSelectElement
    const newTags = screen.getByLabelText('Теги') as HTMLSelectElement
    expect(Array.from(newAccount.options).map((option) => option.value)).toEqual(['', '3'])
    expect(Array.from(newCategory.options).map((option) => option.value)).toEqual(['', '4'])
    expect(Array.from(newTags.options).map((option) => option.value)).toEqual(['6'])
  })
})

describe('plan item reconciliation integration', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    fetchMock.mockClear()
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'POST' && path === '/api/v1/plan-items') return jsonResponse({ id: 22 })
      if (init?.method === 'POST' && path === '/api/v1/plan-items/21/matches') return jsonResponse({ id: 40 })
      if (init?.method === 'PATCH' && path === '/api/v1/plan-items/21') return jsonResponse({ id: 21, version: 2 })
      if (init?.method === 'DELETE' && path === '/api/v1/plan-items/21?version=1') return new Response(null, { status: 204 })
      if (path === '/api/v1/plan-items?kind=expense') return jsonResponse({ items: [{ id: 21, kind: 'expense', title: 'Аренда', amount_minor: 2_000_000, date: '2026-09-25', recurrence: 'none', certainty: 'confirmed', status: 'planned', version: 1 }], total: 1 })
      if (path === '/api/v1/transactions?limit=500&offset=0') return jsonResponse({ items: [
        { id: 30, type: 'expense', amount_minor: 800_000, date: '2026-09-10', account_id: 3, description: 'Уже сверено', matched_plan_item_id: 18, matched_occurrence_month: '2026-09', matched_amount_minor: 800_000, match_completed: true },
        { id: 31, type: 'expense', amount_minor: 1_200_000, date: '2026-09-21', account_id: 3, description: 'Перевод арендодателю', matched_plan_item_id: null },
        { id: 32, type: 'income', amount_minor: 3_000_000, date: '2026-09-20', account_id: 3, description: 'Зарплата', matched_plan_item_id: null },
      ], total: 3, limit: 500, offset: 0 })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({ items: [{ id: 3, name: 'Карта', archived: false, version: 1 }], total: 1 })
      if (path === '/api/v1/categories?include_archived=true') return jsonResponse({ items: [{ id: 4, name: 'Жильё', kind: 'expense', archived: false, version: 1 }], total: 1 })
      if (path === '/api/v1/tags?include_archived=true') return jsonResponse({ items: [{ id: 8, name: 'Обязательное', archived: false, version: 1 }], total: 1 })
      if (path === '/api/v1/loans?include_archived=true') return jsonResponse({ items: [{ id: 7, name: 'Ипотека', schedule_mode: 'auto', archived: false }], total: 1 })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('sends selected tags when creating a plan item', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="payment" /></QueryClientProvider>)

    await screen.findByText('Аренда')
    fireEvent.click(screen.getByRole('button', { name: 'Добавить платеж' }))
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Интернет' } })
    fireEvent.change(screen.getByLabelText(/^(Сумма|Списать)/), { target: { value: '900' } })
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-09-28' } })
    fireEvent.change(screen.getByLabelText('Счёт'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Категория'), { target: { value: '4' } })
    const tags = screen.getByLabelText('Теги') as HTMLSelectElement
    tags.options[0].selected = true
    fireEvent.change(tags)
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/plan-items' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/plan-items' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual(expect.objectContaining({
      kind: 'expense', title: 'Интернет', amount_minor: 90_000, account_id: 3, category_id: 4, tag_ids: [8],
    }))
  })

  it('links a planned payment to a loan', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="payment" /></QueryClientProvider>)

    await screen.findByText('Аренда')
    fireEvent.click(screen.getByRole('button', { name: 'Добавить платеж' }))
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Ипотека' } })
    fireEvent.change(screen.getByLabelText(/^(Сумма|Списать)/), { target: { value: '1 500' } })
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-10-15' } })
    fireEvent.change(screen.getByLabelText('Кредит'), { target: { value: '7' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/plan-items' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/plan-items' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual(expect.objectContaining({ loan_id: 7 }))
  })

  it('offers only unmatched facts and posts a completed plan match idempotently', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="payment" /></QueryClientProvider>)

    await screen.findByText('Аренда')
    fireEvent.click(screen.getByRole('button', { name: 'Сверить с фактом Аренда' }))
    const factSelect = await screen.findByLabelText('Несверенная операция')
    expect(screen.queryByRole('option', { name: /Уже сверено/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Зарплата/ })).not.toBeInTheDocument()
    fireEvent.change(factSelect, { target: { value: '31' } })
    expect(screen.getByLabelText(/Сумма сверки/)).toHaveValue('12000,00')
    expect(screen.getByLabelText('Месяц плана')).toHaveValue('2026-09')
    fireEvent.click(screen.getByLabelText('План исполнен полностью'))
    fireEvent.click(screen.getByRole('button', { name: 'Сверить' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/plan-items/21/matches' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/plan-items/21/matches' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual({ transaction_id: 31, occurrence_month: '2026-09', amount_minor: 1_200_000, completed: true })
    expect(new Headers(request?.headers).get('Idempotency-Key')).toMatch(/^plan-match-/)
  })

  it('edits, cancels and deletes a plan item through versioned endpoints', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="payment" /></QueryClientProvider>)

    await screen.findByText('Аренда')
    fireEvent.click(screen.getByRole('button', { name: 'Изменить Аренда' }))
    expect(screen.getByLabelText('Дата')).toHaveAttribute('readonly')
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Аренда квартиры' } })
    fireEvent.change(screen.getByLabelText(/^(Сумма|Списать)/), { target: { value: '21 000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/plan-items/21' && request?.method === 'PATCH')).toBe(true))
    const [, editRequest] = fetchMock.mock.calls.find(([url, request]) => url === '/api/v1/plan-items/21' && request?.method === 'PATCH')!
    expect(JSON.parse(String(editRequest?.body))).toEqual(expect.objectContaining({ title: 'Аренда квартиры', amount_minor: 2_100_000, version: 1 }))

    fireEvent.click(await screen.findByRole('button', { name: 'Отменить Аренда' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/plan-items/21' && request?.method === 'PATCH' && JSON.parse(String(request.body)).status === 'cancelled')).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Удалить Аренда' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/plan-items/21?version=1' && request?.method === 'DELETE')).toBe(true))
  })
})

describe('loan schedule integration', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    fetchMock.mockClear()
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'POST' && path === '/api/v1/loans/7/schedule/11/payments') return jsonResponse({ transaction_id: 50 })
      if (init?.method === 'POST' && path === '/api/v1/loans/7/schedule') return jsonResponse({ id: 12 })
      if (init?.method === 'PATCH' && path === '/api/v1/loans/7') return jsonResponse({ id: 7, version: 2 })
      if (init?.method === 'DELETE' && path === '/api/v1/loans/7?version=1') return new Response(null, { status: 204 })
      if (init?.method === 'PATCH' && path === '/api/v1/loans/7/schedule/11') return jsonResponse({ id: 11, version: 2 })
      if (init?.method === 'DELETE' && path === '/api/v1/loans/7/schedule/11?version=1') return new Response(null, { status: 204 })
      if (path === '/api/v1/loans?include_archived=true') return jsonResponse({ items: [{ id: 7, name: 'Ипотека', creditor: 'Банк', principal_minor: 8_000_000, account_id: 3, archived: false, version: 1 }], total: 1 })
      if (path === '/api/v1/loans/7/schedule') return jsonResponse({ items: [{ id: 11, loan_id: 7, due_date: '2026-10-15', amount_minor: 123_400, principal_minor: 100_000, interest_minor: 23_400, status: 'planned', paid_minor: 0, version: 1 }], total: 1 })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({ items: [{ id: 3, name: 'Карта', archived: false, version: 1 }], total: 1 })
      if (path === '/api/v1/categories?include_archived=true') return jsonResponse({ items: [{ id: 4, name: 'Кредит', kind: 'expense', archived: false, version: 1 }], total: 1 })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shows a loan schedule and adds a manually entered row', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="loan" /></QueryClientProvider>)

    await screen.findByText('Ипотека')
    fireEvent.click(screen.getByRole('button', { name: 'График кредита Ипотека' }))
    expect((await screen.findAllByText('1 234 ₽')).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('Запланирован')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Добавить строку' }))
    fireEvent.change(screen.getByLabelText('Дата платежа'), { target: { value: '2026-11-15' } })
    fireEvent.change(screen.getByLabelText('Сумма платежа'), { target: { value: '1 500' } })
    fireEvent.change(screen.getByLabelText('В составе основной долг'), { target: { value: '1 200' } })
    fireEvent.change(screen.getByLabelText('В составе проценты'), { target: { value: '300' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить строку' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/loans/7/schedule' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/loans/7/schedule' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual({ due_date: '2026-11-15', amount_minor: 150_000, principal_minor: 120_000, interest_minor: 30_000 })
  })

  it('shows the annuity breakdown and previews shorter-term prepayment', async () => {
    const baseline = {
      regular_payment_minor: 55_000, interest_minor: 10_000, principal_minor: 100_000,
      total_minor: 110_000, payoff_date: '2026-11-15',
      rows: [
        { due_date: '2026-10-15', payment_minor: 55_000, interest_minor: 6_000, principal_minor: 49_000, remaining_principal_minor: 51_000, early_principal_minor: 0 },
        { due_date: '2026-11-15', payment_minor: 55_000, interest_minor: 4_000, principal_minor: 51_000, remaining_principal_minor: 0, early_principal_minor: 0 },
      ],
    }
    fetchMock.mockImplementation(async (input) => {
      const path = String(input)
      if (path === '/api/v1/loans?include_archived=true') return jsonResponse({ items: [{ id: 7, name: 'Ипотека', schedule_mode: 'auto', interest_method: 'simple', principal_minor: 100_000, archived: false, version: 1 }], total: 1 })
      if (path === '/api/v1/loans/7/projection') return jsonResponse({ baseline })
      if (path.startsWith('/api/v1/loans/7/projection?')) return jsonResponse({ baseline, scenario: { ...baseline, interest_minor: 7_000, payoff_date: '2026-10-15', rows: [baseline.rows[0]] }, interest_savings_minor: 3_000 })
      if (path === '/api/v1/transactions?loan_id=7&limit=500&offset=0') return jsonResponse({ items: [], total: 0 })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({ items: [], total: 0 })
      if (path === '/api/v1/categories?include_archived=true') return jsonResponse({ items: [], total: 0 })
      throw new Error(`Unexpected request: ${path}`)
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="loan" /></QueryClientProvider>)

    await screen.findByText('Ипотека')
    fireEvent.click(screen.getByRole('button', { name: 'График кредита Ипотека' }))
    expect(await screen.findByText('Будущие проценты')).toBeInTheDocument()
    expect(screen.getByText('Основной долг')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Дата по графику'), { target: { value: '2026-10-15' } })
    fireEvent.change(screen.getByLabelText('Дополнительная сумма'), { target: { value: '100' } })
    fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }))

    await screen.findByText(/Экономия на процентах/)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('early_strategy=reduce_term'))).toBe(true)
  })

  it('records a partial payment and exposes explicit full completion', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="loan" /></QueryClientProvider>)

    await screen.findByText('Ипотека')
    fireEvent.click(screen.getByRole('button', { name: 'График кредита Ипотека' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Внести платёж' }))
    expect(screen.getByLabelText('Фактическая сумма')).toHaveValue('1234,00')
    expect(screen.getByLabelText('Закрыть строку полностью')).not.toBeChecked()
    fireEvent.change(screen.getByLabelText('Дата списания'), { target: { value: '2026-10-15' } })
    fireEvent.change(screen.getByLabelText('Фактическая сумма'), { target: { value: '500' } })
    fireEvent.change(screen.getByLabelText('В составе основной долг'), { target: { value: '400' } })
    fireEvent.change(screen.getByLabelText('В составе проценты'), { target: { value: '100' } })
    fireEvent.change(screen.getByLabelText('Категория'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Провести платёж' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/loans/7/schedule/11/payments' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/loans/7/schedule/11/payments' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual({ amount_minor: 50_000, principal_minor: 40_000, interest_minor: 10_000, date: '2026-10-15', account_id: 3, category_id: 4, completed: false, comment: null })
    expect(new Headers(request?.headers).get('Idempotency-Key')).toMatch(/^loan-payment-/)
  })

  it('edits, archives and deletes a loan with its current version', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="loan" /></QueryClientProvider>)

    await screen.findByText('Ипотека')
    fireEvent.click(screen.getByRole('button', { name: 'Изменить Ипотека' }))
    expect(screen.getByLabelText('Название')).toHaveValue('Ипотека')
    fireEvent.change(screen.getByLabelText('Кредитор'), { target: { value: 'Новый банк' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/loans/7' && request?.method === 'PATCH')).toBe(true))
    const [, editRequest] = fetchMock.mock.calls.find(([url, request]) => url === '/api/v1/loans/7' && request?.method === 'PATCH')!
    expect(JSON.parse(String(editRequest?.body))).toEqual(expect.objectContaining({ name: 'Ипотека', creditor: 'Новый банк', principal_minor: 8_000_000, version: 1 }))

    fireEvent.click(await screen.findByRole('button', { name: 'Архивировать Ипотека' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/loans/7' && request?.method === 'PATCH' && JSON.parse(String(request.body)).archived === true)).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Удалить Ипотека' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/loans/7?version=1' && request?.method === 'DELETE')).toBe(true))
  })

  it('reuses the schedule form for edit, cancellation and deletion', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="loan" /></QueryClientProvider>)

    await screen.findByText('Ипотека')
    fireEvent.click(screen.getByRole('button', { name: 'График кредита Ипотека' }))
    fireEvent.click(await screen.findByRole('button', { name: /^Изменить строку/ }))
    expect(screen.getByLabelText('Сумма платежа')).toHaveValue('1234,00')
    fireEvent.change(screen.getByLabelText('Сумма платежа'), { target: { value: '1 300' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/loans/7/schedule/11' && request?.method === 'PATCH')).toBe(true))
    const [, editRequest] = fetchMock.mock.calls.find(([url, request]) => url === '/api/v1/loans/7/schedule/11' && request?.method === 'PATCH')!
    expect(JSON.parse(String(editRequest?.body))).toEqual({ due_date: '2026-10-15', amount_minor: 130_000, principal_minor: 100_000, interest_minor: 23_400, version: 1 })

    fireEvent.click(await screen.findByRole('button', { name: /^Отменить строку/ }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/loans/7/schedule/11' && request?.method === 'PATCH' && JSON.parse(String(request.body)).status === 'cancelled')).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: /^Удалить строку/ }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, request]) => url === '/api/v1/loans/7/schedule/11?version=1' && request?.method === 'DELETE')).toBe(true))
  })

  it('requires restoring an archived loan before opening its schedule', async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input)
      if (path === '/api/v1/loans?include_archived=true') return jsonResponse({
        items: [{ id: 8, name: 'Архивный кредит', archived: true, version: 2 }],
        total: 1,
      })
      if (path === '/api/v1/accounts?include_archived=true') return jsonResponse({ items: [], total: 0 })
      if (path === '/api/v1/categories?include_archived=true') return jsonResponse({ items: [], total: 0 })
      throw new Error(`Unexpected request: ${path}`)
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(<QueryClientProvider client={client}><ResourcePage type="loan" /></QueryClientProvider>)

    await screen.findByText('Архивный кредит')
    expect(screen.queryByRole('button', { name: 'График кредита Архивный кредит' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Восстановить Архивный кредит' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/loans/8/schedule')).toBe(false)
  })
})
