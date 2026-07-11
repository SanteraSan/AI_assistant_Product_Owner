export type DocumentItem = {
  id: string
  fileName: string
  sourceType: string
  status: 'uploaded' | 'indexing' | 'indexed' | 'error'
  uploadedAt: string
}

export const mockDocuments: DocumentItem[] = [
  {
    id: 'doc-1',
    fileName: 'product-requirements.pdf',
    sourceType: 'pdf',
    status: 'indexed',
    uploadedAt: '2026-07-11 18:40',
  },
  {
    id: 'doc-2',
    fileName: 'analytics-table.xlsx',
    sourceType: 'xlsx',
    status: 'indexing',
    uploadedAt: '2026-07-11 18:47',
  },
]
