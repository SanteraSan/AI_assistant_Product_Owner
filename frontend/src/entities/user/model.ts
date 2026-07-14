export type UserRole = 'admin' | 'analyst' | 'viewer' | 'ingestion_manager' | 'model_manager'

export type User = {
  id: string
  tenantId: string
  displayName: string
  email: string
  roles: UserRole[]
}
