import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, asList, download, jsonBody, queryString } from './api'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { 'content-type': 'application/json', ...init.headers },
  })
}

describe('api client', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    document.cookie = 'csrf_token=; Max-Age=0; path=/'
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('prefixes API paths and sends JSON mutations with credentials and decoded CSRF', async () => {
    document.cookie = 'csrf_token=part%3Done%3Dtwo; path=/'
    fetchMock.mockResolvedValue(jsonResponse({ id: 7 }))

    await expect(api<{ id: number }>('accounts', {
      method: 'post',
      body: jsonBody({ name: 'Карта' }),
    })).resolves.toEqual({ id: 7 })

    const [url, init] = fetchMock.mock.calls[0]
    const headers = new Headers(init?.headers)
    expect(url).toBe('/api/v1/accounts')
    expect(init).toMatchObject({ method: 'POST', credentials: 'include' })
    expect(headers.get('content-type')).toBe('application/json')
    expect(headers.get('x-csrf-token')).toBe('part=one=two')
  })

  it('does not force a content type for multipart forms', async () => {
    document.cookie = 'csrf_token=token; path=/'
    fetchMock.mockResolvedValue(jsonResponse({ batch_id: 3 }))
    const form = new FormData()
    form.append('file', new File(['date,amount'], 'items.csv', { type: 'text/csv' }))

    await api('/imports/preview', { method: 'POST', body: form })

    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(headers.has('content-type')).toBe(false)
    expect(headers.get('x-csrf-token')).toBe('token')
  })

  it('preserves the structured backend error contract', async () => {
    fetchMock.mockResolvedValue(jsonResponse({
      code: 'validation_error',
      message: 'Validation failed',
      field_errors: [{ field: 'body.amount_minor', message: 'Input should be greater than 0' }],
      request_id: 'request-42',
    }, { status: 422 }))

    const result = api('/transactions')
    await expect(result).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      code: 'validation_error',
      requestId: 'request-42',
      message: 'Validation failed: Input should be greater than 0',
      fieldErrors: [{ field: 'body.amount_minor', message: 'Input should be greater than 0' }],
    } satisfies Partial<ApiError>)
  })

  it('accepts successful responses without a body', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await expect(api('/auth/logout', { method: 'POST' })).resolves.toBeUndefined()
  })

  it('downloads from the versioned API and honors an encoded server filename', async () => {
    vi.useFakeTimers()
    fetchMock.mockResolvedValue(new Response(new Blob(['archive']), {
      headers: { 'content-disposition': "attachment; filename*=UTF-8''budget%20copy.zip" },
    }))
    const createObjectURL = vi.fn(() => 'blob:download')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

    await download('/exports/project', 'fallback.zip')
    vi.runAllTimers()

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/exports/project', { credentials: 'include' })
    expect(click).toHaveBeenCalledOnce()
    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:download')
  })
})

describe('API collection helpers', () => {
  it('supports both arrays and paginated responses', () => {
    expect(asList([1, 2])).toEqual([1, 2])
    expect(asList({ items: [3], total: 1 })).toEqual([3])
    expect(asList(undefined)).toEqual([])
  })

  it('keeps false and zero query values while omitting undefined', () => {
    expect(queryString({ from_month: '2026-09', months: 0, include_possible: false, empty: undefined }))
      .toBe('from_month=2026-09&months=0&include_possible=false')
  })
})
