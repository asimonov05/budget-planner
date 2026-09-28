import type { ListResponse } from './types'

export interface ApiFieldError {
  field?: string
  message?: string
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public details?: unknown,
    public code?: string,
    public fieldErrors: ApiFieldError[] = [],
    public requestId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

interface ErrorPayload {
  code?: string
  detail?: unknown
  message?: unknown
  field_errors?: ApiFieldError[]
  request_id?: string
}

function apiPath(path: string) {
  return path.startsWith('/api/') ? path : `/api/v1${path.startsWith('/') ? path : `/${path}`}`
}

function cookie(name: string) {
  const prefix = `${name}=`
  const value = document.cookie.split(';').map((item) => item.trim()).find((item) => item.startsWith(prefix))?.slice(prefix.length)
  if (!value) return undefined
  try { return decodeURIComponent(value) } catch { return undefined }
}

function responseMessage(body: unknown, status: number) {
  if (typeof body === 'string' && body.trim()) return body
  if (body && typeof body === 'object') {
    const payload = body as ErrorPayload
    const primary = typeof payload.message === 'string' ? payload.message : typeof payload.detail === 'string' ? payload.detail : undefined
    const fieldMessage = payload.field_errors?.find((item) => typeof item.message === 'string')
    if (fieldMessage?.message) return `${primary ?? 'Проверьте введённые данные'}: ${fieldMessage.message}`
    if (primary) return primary
  }
  if (status === 401) return 'Требуется вход в приложение'
  return 'Не удалось выполнить запрос'
}

async function responseBody(response: Response) {
  if (response.status === 204 || response.status === 205) return undefined
  const text = await response.text()
  if (!text) return undefined
  if (!response.headers.get('content-type')?.includes('json')) return text
  try { return JSON.parse(text) as unknown } catch { return text }
}

function errorFromResponse(response: Response, body: unknown) {
  const payload = body && typeof body === 'object' ? body as ErrorPayload : undefined
  return new ApiError(
    response.status,
    responseMessage(body, response.status),
    body,
    payload?.code,
    Array.isArray(payload?.field_errors) ? payload.field_errors : [],
    payload?.request_id ?? response.headers.get('x-request-id') ?? undefined,
  )
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  const isForm = options.body instanceof FormData
  if (options.body && !isForm && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const method = (options.method ?? 'GET').toUpperCase()
  const csrf = cookie('csrf_token')
  if (csrf && !['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set('X-CSRF-Token', csrf)
  const response = await fetch(apiPath(path), { ...options, method, headers, credentials: 'include' })
  const body = await responseBody(response)
  if (!response.ok) throw errorFromResponse(response, body)
  return body as T
}

export function jsonBody(value: unknown) { return JSON.stringify(value) }
export function asList<T>(data: T[] | ListResponse<T> | undefined): T[] { return Array.isArray(data) ? data : data?.items ?? [] }
export function queryString(values: Record<string, string | number | boolean | undefined>) {
  const search = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => value !== undefined && search.set(key, String(value)))
  return search.toString()
}

export async function download(path: string, fallbackName: string) {
  const response = await fetch(apiPath(path), { credentials: 'include' })
  if (!response.ok) throw errorFromResponse(response, await responseBody(response))
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition')
  const filename = disposition?.match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i)?.[1] ?? fallbackName
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a'); anchor.href = url
  try { anchor.download = decodeURIComponent(filename) } catch { anchor.download = fallbackName }
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
