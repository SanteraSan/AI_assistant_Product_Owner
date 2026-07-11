import { apiRequest } from '../../shared/api/httpClient'
import type { User } from '../user/model'
import type { DocumentItem } from './model'

type DocumentDto = {
  id: string
  file_name: string
  source_type: string
  status: DocumentItem['status']
  created_at: string
}

export async function fetchBucketDocuments(
  user: User,
  bucketId: string,
): Promise<DocumentItem[]> {
  const documents = await apiRequest<DocumentDto[]>(`/buckets/${bucketId}/documents`, {
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return documents.map((document) => ({
    id: document.id,
    fileName: document.file_name,
    sourceType: document.source_type,
    status: document.status,
    uploadedAt: new Date(document.created_at).toLocaleString('ru-RU'),
  }))
}

export async function uploadDocument(
  user: User,
  bucketId: string,
  file: File,
): Promise<DocumentItem> {
  const document = await apiRequest<DocumentDto>(`/buckets/${bucketId}/documents/upload`, {
    body: await file.arrayBuffer(),
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      'X-File-Name': file.name,
    },
    json: false,
    method: 'POST',
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return {
    id: document.id,
    fileName: document.file_name,
    sourceType: document.source_type,
    status: document.status,
    uploadedAt: new Date(document.created_at).toLocaleString('ru-RU'),
  }
}
