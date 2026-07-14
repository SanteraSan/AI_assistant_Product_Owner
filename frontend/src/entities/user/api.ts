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

export async function logoutAuth(): Promise<void> {
  await apiRequest<{ ok: boolean }>('/auth/logout', { method: 'POST' })
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

export function buildLoginUrl(returnTo: string = window.location.pathname || '/'): string {
  const params = new URLSearchParams({ return_to: returnTo })
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
