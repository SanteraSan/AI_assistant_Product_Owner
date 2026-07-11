import { apiRequest } from '../../shared/api/httpClient'
import type { User } from '../user/model'
import type { DocumentItem } from './model'

type DocumentDto = {
  id: string
  bucket_id?: string | null
  owner_user_id?: string | null
  title: string
  file_name: string
  source_type: string
  status: DocumentItem['status']
  visibility: DocumentItem['visibility']
  allowed_roles: string[]
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
  return documents.map(mapDocument)
}

export async function fetchAvailableDocuments(user: User): Promise<DocumentItem[]> {
  const documents = await apiRequest<DocumentDto[]>('/documents/available', {
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return documents.map(mapDocument)
}

export async function fetchMyDocuments(user: User): Promise<DocumentItem[]> {
  const documents = await apiRequest<DocumentDto[]>('/documents/my', {
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return documents.map(mapDocument)
}

export async function addDocumentToBucket(
  user: User,
  bucketId: string,
  documentId: string,
): Promise<DocumentItem> {
  const document = await apiRequest<DocumentDto>(`/buckets/${bucketId}/documents/${documentId}`, {
    method: 'POST',
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return mapDocument(document)
}

export async function removeDocumentFromBucket(
  user: User,
  bucketId: string,
  documentId: string,
): Promise<void> {
  await apiRequest<void>(`/buckets/${bucketId}/documents/${documentId}`, {
    method: 'DELETE',
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
}

function mapDocument(document: DocumentDto): DocumentItem {
  return {
    id: document.id,
    bucketId: document.bucket_id,
    ownerUserId: document.owner_user_id,
    title: document.title,
    fileName: document.file_name,
    sourceType: document.source_type,
    status: document.status,
    visibility: document.visibility,
    allowedRoles: document.allowed_roles,
    uploadedAt: new Date(document.created_at).toLocaleString('ru-RU'),
  }
}

export async function uploadDocument(
  user: User,
  bucketId: string,
  file: File,
  visibility: DocumentItem['visibility'] = 'private',
): Promise<DocumentItem> {
  const document = await apiRequest<DocumentDto>(`/buckets/${bucketId}/documents/upload`, {
    body: await file.arrayBuffer(),
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      'X-Document-Visibility': visibility,
      'X-File-Name': file.name,
    },
    json: false,
    method: 'POST',
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return mapDocument(document)
}
