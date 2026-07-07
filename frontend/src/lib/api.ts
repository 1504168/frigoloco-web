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
 */

const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8100'
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

  const response = await fetch(url, {
    method,
    headers,
    body: hasBody ? JSON.stringify(body) : undefined,
    signal: options?.signal,
  })

  if (!response.ok) {
    throw await toApiError(response)
  }

  // 204 No Content or empty body.
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }
  const text = await response.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
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
