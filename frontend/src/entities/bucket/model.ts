export type Bucket = {
  id: string
  name: string
  description: string
  documentCount: number
  status: 'ready' | 'indexing' | 'error'
}

export const mockBuckets: Bucket[] = [
  {
    id: 'taskflow_seed',
    name: 'TaskFlow Knowledge Base',
    description: 'Основной demo bucket с проектной документацией и fixtures.',
    documentCount: 42,
    status: 'ready',
  },
  {
    id: 'm5_documents',
    name: 'M5 Document Regression',
    description: 'PDF, DOCX, Excel и multimodal документы для проверок ingestion.',
    documentCount: 18,
    status: 'indexing',
  },
]
