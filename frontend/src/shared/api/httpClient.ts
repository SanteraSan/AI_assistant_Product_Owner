import { API_BASE_URL } from '../config/env'

type RequestOptions = RequestInit & {
  json?: boolean
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

export async function apiRequest<TResponse>(
  path: string,
  options: RequestOptions = {},
): Promise<TResponse> {
  const headers = new Headers(options.headers)
  if (options.json !== false) {
    headers.set('Content-Type', headers.get('Content-Type') ?? 'application/json')
  }

  const method = (options.method ?? 'GET').toUpperCase()
  if (!SAFE_METHODS.has(method)) {
    // Lazy import avoids circular dependency with entities/user/store.
    const { useAuthStore } = await import('../../entities/user/store')
    const csrfToken = useAuthStore.getState().csrfToken
    if (csrfToken) {
      headers.set('X-CSRF-Token', csrfToken)
    }
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  })

  if (!response.ok) {
    const details = await response.text()
    throw new Error(details || `Request failed with status ${response.status}`)
  }

  if (response.status === 204) {
    return undefined as TResponse
  }

  return response.json() as Promise<TResponse>
}
