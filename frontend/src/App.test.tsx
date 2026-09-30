import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { Login } from './pages/Login'
import { Register } from './pages/Register'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { 'content-type': 'application/json', ...init.headers },
  })
}

function queryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

describe('authentication UI', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('redirects a protected route when the shared current-user query resolves to null', async () => {
    fetchMock.mockResolvedValue(jsonResponse({
      code: 'http_error', message: 'Not authenticated', field_errors: [], request_id: 'auth-1',
    }, { status: 401 }))
    const client = queryClient()

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/']}><App /></MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: 'Вход в бюджет' })).toBeInTheDocument()
    expect(client.getQueryData(['me'])).toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('submits credentials once, caches the returned user, and navigates after success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({
      user: { id: 1, username: 'owner' }, csrf_token: 'csrf-value',
    }))
    const client = queryClient()
    client.setQueryData(['accounts'], { items: [{ id: 1, name: 'Чужой счёт' }] })

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/login']}>
          <Routes>
            <Route path="/login" element={<Login currentUser={null} />} />
            <Route path="/" element={<h1>Бюджет открыт</h1>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    fireEvent.change(screen.getByLabelText('Логин'), { target: { value: 'owner' } })
    fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Войти' }))

    expect(await screen.findByRole('heading', { name: 'Бюджет открыт' })).toBeInTheDocument()
    expect(client.getQueryData(['me'])).toEqual({ id: 1, username: 'owner' })
    expect(client.getQueryData(['accounts'])).toBeUndefined()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/auth/login')
    expect(init).toMatchObject({ method: 'POST', credentials: 'include', body: JSON.stringify({ username: 'owner', password: 'secret' }) })
  })

  it('shows client-side required-field errors without calling the API', async () => {
    const client = queryClient()
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter><Login currentUser={null} /></MemoryRouter>
      </QueryClientProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Войти' }))

    await waitFor(() => expect(screen.getByText('Введите логин')).toBeInTheDocument())
    expect(screen.getByText('Введите пароль')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('opens registration from login, creates an account, and signs in', async () => {
    fetchMock.mockResolvedValue(jsonResponse({
      user: { id: 2, username: 'alice', is_admin: false }, csrf_token: 'new-csrf',
    }))
    const client = queryClient()
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/login']}>
          <Routes>
            <Route path="/login" element={<Login currentUser={null} />} />
            <Route path="/register" element={<Register currentUser={null} />} />
            <Route path="/" element={<h1>Личный бюджет открыт</h1>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByRole('link', { name: 'Зарегистрироваться' }))
    expect(await screen.findByRole('heading', { name: 'Новый аккаунт' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Логин'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'a strong registration password' } })
    fireEvent.change(screen.getByLabelText('Повторите пароль'), { target: { value: 'a strong registration password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Создать аккаунт' }))
    expect(await screen.findByRole('heading', { name: 'Личный бюджет открыт' })).toBeInTheDocument()
    expect(client.getQueryData(['me'])).toEqual({ id: 2, username: 'alice', is_admin: false })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/auth/register')
    expect(init).toMatchObject({ method: 'POST', body: JSON.stringify({ username: 'alice', password: 'a strong registration password' }) })
  })

  it('requires matching registration passwords before calling the API', async () => {
    const client = queryClient()
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter><Register currentUser={null} /></MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.change(screen.getByLabelText('Логин'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'a strong registration password' } })
    fireEvent.change(screen.getByLabelText('Повторите пароль'), { target: { value: 'another strong password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Создать аккаунт' }))
    expect(await screen.findByText('Пароли не совпадают')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
