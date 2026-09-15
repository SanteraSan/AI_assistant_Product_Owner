import { API_BASE_URL } from '../config/env'

type RequestOptions = RequestInit & {
  json?: boolean
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

export class ApiError extends Error {
  readonly status: number
  readonly errorType?: string
  readonly reason?: string
  readonly detail?: unknown

  constructor(
    message: string,
    {
      status,
      errorType,
      reason,
      detail,
    }: {
      status: number
      errorType?: string
      reason?: string
      detail?: unknown
    },
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.errorType = errorType
    this.reason = reason
    this.detail = detail
  }
}

export function formatApiError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.errorType === 'external_scope_not_synthetic') {
      return (
        'Внешняя модель в этом чате недоступна: сюда уже попадали ваши документы ' +
        'или не-synthetic evidence. Откройте новый чат.'
      )
    }
    if (error.errorType === 'external_agent_not_supported') {
      return 'В этом срезе Agent работает только на Ollama. Выберите Гибрид или Только локальные.'
    }
    if (error.errorType === 'model_unavailable') {
      return 'Эта модель сейчас недоступна. Проверьте подход, ключ провайдера или выберите другую модель.'
    }
    if (typeof error.detail === 'string' && error.detail.trim()) {
      return error.detail
    }
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return fallback
}

export async function apiRequest<TResponse>(
  path: string,
  options: RequestOptions = {},
): Promise<TResponse> {
  const headers = applyRequestHeaders(options)

  const method = (options.method ?? 'GET').toUpperCase()
  await applyCsrfHeader(headers, method)

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  })

  if (!response.ok) {
    const details = await response.text()
    let errorType: string | undefined
    let reason: string | undefined
    let detail: unknown = details
    let message = details || `Request failed with status ${response.status}`
    try {
      const parsed = JSON.parse(details) as {
        detail?: unknown
        error_type?: string
        reason?: string
      }
      errorType = parsed.error_type
      reason = parsed.reason
      detail = parsed.detail ?? details
      if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
        message = parsed.detail
      }
    } catch {
      // Keep raw text for non-JSON error bodies.
    }
    throw new ApiError(message, {
      status: response.status,
      errorType,
      reason,
      detail,
    })
  }

  if (response.status === 204) {
    return undefined as TResponse
  }

  return response.json() as Promise<TResponse>
}

function applyRequestHeaders(options: RequestOptions): Headers {
  const headers = new Headers(options.headers)
  if (options.json !== false) {
    headers.set('Content-Type', headers.get('Content-Type') ?? 'application/json')
  }
  return headers
}

async function applyCsrfHeader(headers: Headers, method: string): Promise<void> {
  if (SAFE_METHODS.has(method)) {
    return
  }
  const { useAuthStore } = await import('../../entities/user/store')
  const csrfToken = useAuthStore.getState().csrfToken
  if (csrfToken) {
    headers.set('X-CSRF-Token', csrfToken)
  }
}

export function filenameFromContentDisposition(header: string | null): string | null {
  if (!header) {
    return null
  }
  const utfMatch = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (utfMatch?.[1]) {
    return decodeURIComponent(utfMatch[1])
  }
  const quotedMatch = /filename="([^"]+)"/i.exec(header)
  if (quotedMatch?.[1]) {
    return quotedMatch[1]
  }
  return null
}

export function saveBlob(blob: Blob, fileName: string): void {
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = fileName
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(objectUrl)
}

export async function apiRequestBlob(
  path: string,
  options: RequestOptions = {},
): Promise<{ blob: Blob; fileName: string | null }> {
  const headers = applyRequestHeaders(options)
  const method = (options.method ?? 'GET').toUpperCase()
  await applyCsrfHeader(headers, method)

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  })

  if (!response.ok) {
    const details = await response.text()
    let message = details || `Request failed with status ${response.status}`
    let errorType: string | undefined
    let reason: string | undefined
    let detail: unknown = details
    try {
      const parsed = JSON.parse(details) as {
        detail?: unknown
        error_type?: string
        reason?: string
      }
      errorType = parsed.error_type
      reason = parsed.reason
      detail = parsed.detail ?? details
      if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
        message = parsed.detail
      }
    } catch {
      // Keep raw text for non-JSON error bodies.
    }
    throw new ApiError(message, {
      status: response.status,
      errorType,
      reason,
      detail,
    })
  }

  return {
    blob: await response.blob(),
    fileName: filenameFromContentDisposition(response.headers.get('Content-Disposition')),
  }
}
