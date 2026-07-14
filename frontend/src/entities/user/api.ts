import { apiRequest } from '../../shared/api/httpClient'
import type { User, UserRole } from './model'

export type AuthMeResponse = {
  id: string
  email: string
  displayName: string
  tenantId: string
  roles: string[]
  csrfToken: string
}

export async function fetchAuthMe(): Promise<AuthMeResponse> {
  return apiRequest<AuthMeResponse>('/auth/me')
}

export async function logoutAuth(): Promise<{ ok: boolean; logoutUrl?: string }> {
  return apiRequest<{ ok: boolean; logoutUrl?: string }>('/auth/logout', { method: 'POST' })
}

export function userFromAuthMe(payload: AuthMeResponse): User {
  return {
    id: payload.id,
    email: payload.email,
    displayName: payload.displayName,
    tenantId: payload.tenantId,
    roles: payload.roles.filter(isUserRole),
  }
}

export function buildLoginUrl(
  returnTo: string = window.location.pathname || '/',
  options: { prompt?: 'login' | null } = { prompt: 'login' },
): string {
  const params = new URLSearchParams({ return_to: returnTo })
  if (options.prompt) {
    params.set('prompt', options.prompt)
  }
  return `/auth/login?${params.toString()}`
}

function isUserRole(value: string): value is UserRole {
  return (
    value === 'admin' ||
    value === 'analyst' ||
    value === 'viewer' ||
    value === 'ingestion_manager' ||
    value === 'model_manager'
  )
}
