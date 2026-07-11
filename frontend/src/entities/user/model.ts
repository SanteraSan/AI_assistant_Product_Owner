export type UserRole = 'admin' | 'analyst' | 'viewer' | 'ingestion_manager' | 'model_manager'

export type User = {
  id: string
  tenantId: string
  displayName: string
  email: string
  roles: UserRole[]
}

export const mockUser: User = {
  id: 'local-user-1',
  tenantId: 'local_demo',
  displayName: 'Петров И.И.',
  email: 'petrov@example.local',
  roles: ['admin', 'analyst', 'ingestion_manager', 'model_manager'],
}
