import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GoalsPage } from './Goals'

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><GoalsPage /></QueryClientProvider>)
}

describe('goal reserve operations', () => {
  const fetchMock = vi.fn<typeof fetch>()
  let deleteStatus = 204
  let activeReservedMinor = 30_000_00

  beforeEach(() => {
    deleteStatus = 204
    activeReservedMinor = 30_000_00
    fetchMock.mockReset()
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input)
      if (init?.method === 'DELETE' && path === '/api/v1/goals/7?version=4') {
        if (deleteStatus === 409) return new Response(JSON.stringify({ detail: 'Goal has history' }), { status: 409, headers: { 'content-type': 'application/json' } })
        return new Response(null, { status: 204 })
      }
      if (init?.method === 'PATCH' && path === '/api/v1/goals/7') {
        return jsonResponse({ id: 7, ...JSON.parse(String(init.body)), reserved_minor: 30_000_00, version: 5 })
      }
      if (init?.method === 'PATCH' && path === '/api/v1/goals/8') {
        return jsonResponse({ id: 8, ...JSON.parse(String(init.body)), reserved_minor: 0, version: 3 })
      }
      if (init?.method === 'POST' && path === '/api/v1/goals/7/allocations') {
        return jsonResponse({ id: 21, goal_id: 7, ...JSON.parse(String(init.body)) })
      }
      if (path === '/api/v1/goals?include_archived=true') return jsonResponse({
        items: [{
          id: 8,
          name: 'Старая цель',
          target_amount_minor: 50_000_00,
          reserved_minor: 0,
          remaining_need_minor: 50_000_00,
          priority: 3,
          status: 'archived',
          archived: true,
          version: 2,
        }],
        total: 1,
      })
      if (path === '/api/v1/goals') return jsonResponse({
        items: [{
          id: 7,
          name: 'Отпуск',
          target_amount_minor: 150_000_00,
          reserved_minor: activeReservedMinor,
          remaining_need_minor: 150_000_00 - activeReservedMinor,
          target_date: '2027-06-01',
          priority: 2,
          color: '#6b8f71',
          status: 'active',
          archived: false,
          version: 4,
        }],
        total: 1,
      })
      if (path === '/api/v1/accounts') return jsonResponse({
        items: [
          { id: 3, name: 'Карта', current_balance_minor: 100_000_00, archived: false },
          { id: 9, name: 'Старый счёт', current_balance_minor: 0, archived: true },
        ],
        total: 2,
      })
      if (path === '/api/v1/categories') return jsonResponse({
        items: [
          { id: 4, name: 'Путешествия', kind: 'expense', archived: false },
          { id: 5, name: 'Зарплата', kind: 'income', archived: false },
          { id: 6, name: 'Старая категория', kind: 'expense', archived: true },
        ],
        total: 3,
      })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('creates an atomic goal expense with explicit shortfall consent and expense details', async () => {
    renderPage()

    await screen.findByText('Отпуск')
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/accounts')).toBe(true)
      expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/categories')).toBe(true)
    })
    fireEvent.click(screen.getByRole('button', { name: 'Изменить резерв' }))
    fireEvent.click(screen.getByLabelText('Оплатить'))

    expect(screen.getByText(/Свободные деньги не уменьшатся повторно/)).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Зарплата' })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Старый счёт' })).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить' }))
    expect(await screen.findByText('Укажите сумму больше нуля')).toBeInTheDocument()
    expect(screen.getByText('Укажите дату')).toBeInTheDocument()
    expect(screen.getByText('Выберите счёт')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/goals/7/allocations' && init?.method === 'POST')).toBe(false)

    fireEvent.change(screen.getByLabelText('Сумма'), { target: { value: '40 000' } })
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-10-03' } })
    fireEvent.change(screen.getByLabelText('Счёт'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Категория расхода'), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText('Описание операции'), { target: { value: '  Авиабилеты  ' } })
    fireEvent.change(screen.getByLabelText('Комментарий'), { target: { value: '  Билеты на отпуск  ' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /Разрешить покрыть нехватку резерва/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/goals/7/allocations' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/goals/7/allocations' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual({
      kind: 'expense',
      amount_minor: 4_000_000,
      date: '2026-10-03',
      comment: 'Билеты на отпуск',
      account_id: 3,
      category_id: 4,
      description: 'Авиабилеты',
      allow_allocate_shortfall: true,
    })
    expect(new Headers(request?.headers).get('Idempotency-Key')).toMatch(/^goal-movement-/)
  })

  it('records a refund into the reserve without classifying it as income', async () => {
    renderPage()

    await screen.findByText('Отпуск')
    fireEvent.click(screen.getByRole('button', { name: 'Изменить резерв' }))
    fireEvent.click(screen.getByLabelText('Вернуть'))

    expect(screen.getByText(/Он не считается новым доходом/)).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /нехватку резерва/ })).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Сумма'), { target: { value: '10 000' } })
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-10-05' } })
    fireEvent.change(screen.getByLabelText('Счёт'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Описание операции'), { target: { value: 'Возврат авиабилетов' } })
    fireEvent.change(screen.getByLabelText('Комментарий'), { target: { value: 'Возврат перевозчика' } })
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/goals/7/allocations' && init?.method === 'POST')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/goals/7/allocations' && init?.method === 'POST')!
    expect(JSON.parse(String(request?.body))).toEqual({
      kind: 'refund',
      amount_minor: 1_000_000,
      date: '2026-10-05',
      comment: 'Возврат перевозчика',
      account_id: 3,
      category_id: null,
      description: 'Возврат авиабилетов',
    })
    expect(new Headers(request?.headers).get('Idempotency-Key')).toMatch(/^goal-movement-/)
  })

  it('keeps allocation and release non-cash semantics and gives each submission a new key', async () => {
    renderPage()

    await screen.findByText('Отпуск')
    fireEvent.click(screen.getByRole('button', { name: 'Изменить резерв' }))
    expect(screen.getByText(/Общий остаток на счетах не меняется/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Сумма'), { target: { value: '5 000' } })
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-10-01' } })
    fireEvent.change(screen.getByLabelText('Комментарий'), { target: { value: 'Плановый взнос' } })
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить' }))

    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => url === '/api/v1/goals/7/allocations' && init?.method === 'POST')).toHaveLength(1))
    await screen.findByRole('button', { name: 'Изменить резерв' })
    fireEvent.click(screen.getByRole('button', { name: 'Изменить резерв' }))
    fireEvent.click(screen.getByLabelText('Освободить'))
    fireEvent.change(screen.getByLabelText('Сумма'), { target: { value: '1 000' } })
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-10-02' } })
    fireEvent.change(screen.getByLabelText('Комментарий'), { target: { value: 'Смена планов' } })
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить' }))

    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => url === '/api/v1/goals/7/allocations' && init?.method === 'POST')).toHaveLength(2))
    const requests = fetchMock.mock.calls.filter(([url, init]) => url === '/api/v1/goals/7/allocations' && init?.method === 'POST')
    expect(JSON.parse(String(requests[0][1]?.body))).toEqual({ kind: 'allocation', amount_minor: 500_000, date: '2026-10-01', comment: 'Плановый взнос' })
    expect(JSON.parse(String(requests[1][1]?.body))).toEqual({ kind: 'release', amount_minor: 100_000, date: '2026-10-02', comment: 'Смена планов' })
    const keys = requests.map(([, request]) => new Headers(request?.headers).get('Idempotency-Key'))
    expect(keys[0]).toMatch(/^goal-movement-/)
    expect(keys[1]).toMatch(/^goal-movement-/)
    expect(keys[0]).not.toBe(keys[1])
  })

  it('edits goal fields using optimistic versioning', async () => {
    renderPage()

    await screen.findByText('Отпуск')
    fireEvent.click(screen.getByRole('button', { name: 'Редактировать цель Отпуск' }))

    expect(screen.getByLabelText('Название')).toHaveValue('Отпуск')
    expect(screen.getByLabelText('Целевая сумма')).toHaveValue('150000,00')
    expect(screen.queryByLabelText('Уже зарезервировано')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Название'), { target: { value: '  Море  ' } })
    fireEvent.change(screen.getByLabelText('Целевая сумма'), { target: { value: '200 000' } })
    fireEvent.change(screen.getByLabelText('Срок'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Приоритет'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Цвет'), { target: { value: '#336699' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/goals/7' && init?.method === 'PATCH')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/goals/7' && init?.method === 'PATCH')!
    expect(JSON.parse(String(request?.body))).toEqual({
      version: 4,
      name: 'Море',
      target_amount_minor: 20_000_000,
      target_date: null,
      priority: 1,
      color: '#336699',
    })
  })

  it('requires an explicit reserve disposition and release date before archiving', async () => {
    renderPage()

    await screen.findByText('Отпуск')
    fireEvent.click(screen.getByRole('button', { name: 'Архивировать цель Отпуск' }))
    fireEvent.click(screen.getByRole('button', { name: 'Архивировать' }))
    expect(await screen.findByText('Выберите, что сделать с резервом')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/goals/7' && init?.method === 'PATCH')).toBe(false)

    fireEvent.click(screen.getByLabelText(/Освободить резерв/))
    fireEvent.click(screen.getByRole('button', { name: 'Архивировать' }))
    expect(await screen.findByText('Укажите дату освобождения')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Дата освобождения'), { target: { value: '2026-10-07' } })
    fireEvent.click(screen.getByRole('button', { name: 'Архивировать' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/goals/7' && init?.method === 'PATCH')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/goals/7' && init?.method === 'PATCH')!
    expect(JSON.parse(String(request?.body))).toEqual({
      version: 4,
      status: 'archived',
      archived: true,
      reserve_disposition: 'release',
      reserve_date: '2026-10-07',
    })
  })

  it('archives a goal without reserve fields when its reserve is zero', async () => {
    activeReservedMinor = 0
    renderPage()

    await screen.findByText('Отпуск')
    fireEvent.click(screen.getByRole('button', { name: 'Архивировать цель Отпуск' }))

    expect(screen.queryByRole('group', { name: 'Судьба резерва' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Архивировать' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/goals/7' && init?.method === 'PATCH')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/goals/7' && init?.method === 'PATCH')!
    expect(JSON.parse(String(request?.body))).toEqual({
      version: 4,
      status: 'archived',
      archived: true,
    })
  })

  it('hard-deletes only through the versioned safe-delete endpoint', async () => {
    renderPage()

    await screen.findByText('Отпуск')
    fireEvent.click(screen.getByRole('button', { name: 'Удалить цель Отпуск' }))
    expect(screen.getByText(/Это действие нельзя отменить/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Удалить навсегда' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/goals/7?version=4' && init?.method === 'DELETE')).toBe(true))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /Удалить цель/ })).not.toBeInTheDocument())
  })

  it('offers archiving when safe deletion is rejected because the goal has history', async () => {
    deleteStatus = 409
    renderPage()

    await screen.findByText('Отпуск')
    fireEvent.click(screen.getByRole('button', { name: 'Удалить цель Отпуск' }))
    fireEvent.click(screen.getByRole('button', { name: 'Удалить навсегда' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('У цели есть резерв или история, поэтому её можно только архивировать.')
    fireEvent.click(screen.getByRole('button', { name: 'Архивировать вместо удаления' }))
    expect(screen.getByRole('dialog', { name: 'Архивировать цель «Отпуск»?' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Судьба резерва' })).toBeInTheDocument()
  })

  it('loads archived goals on demand and restores them with their version', async () => {
    renderPage()

    await screen.findByText('Отпуск')
    expect(screen.queryByText('Старая цель')).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Показывать архивные цели'))

    await screen.findByText('Старая цель')
    expect(screen.getByText('Архив')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/goals?include_archived=true')).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Восстановить цель Старая цель' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/goals/8' && init?.method === 'PATCH')).toBe(true))
    const [, request] = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/goals/8' && init?.method === 'PATCH')!
    expect(JSON.parse(String(request?.body))).toEqual({ version: 2, status: 'active', archived: false })
  })
})
