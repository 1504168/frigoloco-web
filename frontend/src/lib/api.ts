/**
 * Typed fetch client for the FrigoLoco FastAPI backend.
 *
 * Backend conventions (contract every page-agent relies on):
 *   - Base URL from VITE_API_BASE_URL (default http://localhost:8100).
 *   - Routes live under /api/v1.
 *   - List endpoints return a Page<T>: { items, total, limit, offset }.
 *   - Errors return an envelope: { error: { code, message, details? } }.
 *
 * Use the exported get/post/put/patch/del helpers. They throw ApiError on
 * non-2xx responses so react-query surfaces failures to ErrorState.
 *
 * Auth: when a bearer token is stored (see lib/auth), it is attached as
 * `Authorization: Bearer <token>` on every request. Any 401 (except the login
 * call itself) clears the token and redirects to /login.
 */

import { clearToken, getToken } from '@/lib/auth'

const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8100'

/** Login endpoint path; a 401 here means bad credentials, not an expired session. */
const LOGIN_PATH = '/api/v1/auth/login'
/** Route the browser is sent to when a session expires. */
const LOGIN_ROUTE = '/login'
/** Base URL with any trailing slash stripped so path joins are predictable. */
export const API_BASE_URL = RAW_BASE.replace(/\/+$/, '')

/** Shape of a paginated list response from the backend. */
export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

/** Parsed shape of the backend error envelope. */
export interface ApiErrorBody {
  code: string
  message: string
  details?: unknown
}

/** Error thrown for any non-2xx response. Carries the parsed envelope when present. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: unknown

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.details = body.details
  }
}

/** Primitive values accepted as query-string params. */
export type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue>

/** Build a query string, skipping null/undefined values. */
function buildQuery(params?: QueryParams): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue
    search.append(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

/** Turn any thrown/returned failure into a normalized ApiError. */
async function toApiError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody = {
    code: `http_${response.status}`,
    message: response.statusText || 'Request failed',
  }
  try {
    const parsed = (await response.json()) as { error?: ApiErrorBody }
    if (parsed && typeof parsed === 'object' && parsed.error) {
      body = parsed.error
    }
  } catch {
    // Non-JSON error body: keep the status-derived default.
  }
  return new ApiError(response.status, body)
}

interface RequestOptions {
  params?: QueryParams
  signal?: AbortSignal
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options?: RequestOptions,
): Promise<T> {
  const url = `${API_BASE_URL}${path}${buildQuery(options?.params)}`
  const headers: Record<string, string> = { Accept: 'application/json' }
  const hasBody = body !== undefined
  if (hasBody) headers['Content-Type'] = 'application/json'

  addBearerToken(headers)

  const response = await fetch(url, {
    method,
    headers,
    body: hasBody ? JSON.stringify(body) : undefined,
    signal: options?.signal,
  })

  if (!response.ok) {
    throw await toAuthCheckedApiError(path, response)
  }

  // 204 No Content or empty body.
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }
  const text = await response.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

function addBearerToken(headers: Record<string, string>): void {
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
}

/**
 * An expired/invalid session on any endpoint (other than the login call itself)
 * clears the token and bounces to the login page. Guards against a redirect loop
 * when already sitting on /login.
 */
async function toAuthCheckedApiError(path: string, response: Response): Promise<ApiError> {
  if (response.status === 401 && path !== LOGIN_PATH) {
    clearToken()
    if (window.location.pathname !== LOGIN_ROUTE) {
      window.location.href = LOGIN_ROUTE
    }
  }
  return toApiError(response)
}

/** Pull the filename out of a Content-Disposition header, if present. */
function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const utf8Match = header.match(/filename\*=(?:UTF-8'')?["']?([^"';]+)/i)
  if (utf8Match) return decodeURIComponent(utf8Match[1])
  const plainMatch = header.match(/filename=["']?([^"';]+)/i)
  return plainMatch ? plainMatch[1] : null
}

/**
 * GET a file endpoint with the bearer token and save it through a browser
 * download, using the server's Content-Disposition filename when it sends one.
 * Throws ApiError on non-2xx, like the JSON helpers.
 */
export async function downloadFile(
  path: string,
  fallbackFilename: string,
  params?: QueryParams,
): Promise<void> {
  const headers: Record<string, string> = { Accept: '*/*' }
  addBearerToken(headers)
  const response = await fetch(`${API_BASE_URL}${path}${buildQuery(params)}`, { headers })
  if (!response.ok) {
    throw await toAuthCheckedApiError(path, response)
  }
  const blob = await response.blob()
  const filename =
    filenameFromDisposition(response.headers.get('Content-Disposition')) ?? fallbackFilename
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(objectUrl)
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>('GET', path, undefined, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('POST', path, body, options),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('PUT', path, body, options),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('PATCH', path, body, options),
  del: <T>(path: string, options?: RequestOptions) =>
    request<T>('DELETE', path, undefined, options),
}
