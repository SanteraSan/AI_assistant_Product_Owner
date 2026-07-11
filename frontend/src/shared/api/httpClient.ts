import { API_BASE_URL } from '../config/env'

type RequestOptions = RequestInit & {
  json?: boolean
  tenantId?: string
  userId?: string
  roles?: string[]
}

export async function apiRequest<TResponse>(
  path: string,
  options: RequestOptions = {},
): Promise<TResponse> {
  const headers = new Headers(options.headers)
  if (options.json !== false) {
    headers.set('Content-Type', headers.get('Content-Type') ?? 'application/json')
  }

  if (options.tenantId) {
    headers.set('X-Tenant-ID', options.tenantId)
  }
  if (options.userId) {
    headers.set('X-User-ID', options.userId)
  }
  if (options.roles?.length) {
    headers.set('X-User-Roles', options.roles.join(','))
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
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
