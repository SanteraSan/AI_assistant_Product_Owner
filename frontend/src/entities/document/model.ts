export type DocumentItem = {
  id: string
  bucketId?: string | null
  ownerUserId?: string | null
  title: string
  fileName: string
  sourceType: string
  status: 'uploaded' | 'indexing' | 'indexed' | 'error'
  visibility: 'private' | 'role' | 'tenant' | 'team' | 'public'
  allowedRoles: string[]
  uploadedAt: string
}

export const mockDocuments: DocumentItem[] = [
  {
    id: 'doc-1',
    bucketId: 'taskflow_seed',
    ownerUserId: 'local-user-1',
    title: 'product-requirements.pdf',
    fileName: 'product-requirements.pdf',
    sourceType: 'pdf',
    status: 'indexed',
    visibility: 'private',
    allowedRoles: [],
    uploadedAt: '2026-07-11 18:40',
  },
  {
    id: 'doc-2',
    bucketId: 'taskflow_seed',
    ownerUserId: 'local-user-1',
    title: 'analytics-table.xlsx',
    fileName: 'analytics-table.xlsx',
    sourceType: 'xlsx',
    status: 'indexing',
    visibility: 'role',
    allowedRoles: ['analyst'],
    uploadedAt: '2026-07-11 18:47',
  },
]
