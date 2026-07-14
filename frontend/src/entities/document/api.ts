import { apiRequest } from '../../shared/api/httpClient'
import type { User } from '../user/model'
import type { DocumentItem, StagedDocumentItem } from './model'

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

type StagedDocumentDto = {
  id: string
  original_file_name: string
  source_type: string
  status: StagedDocumentItem['status']
  size_bytes: number
  created_at: string
}

type CommitDocumentsDto = {
  documents: DocumentDto[]
  indexing_job_ids: string[]
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

export type DeleteDocumentConflict = {
  reason: 'document_in_use'
  buckets: Array<{
    id: string
    name: string
  }>
}

export async function deleteDocument(user: User, documentId: string): Promise<void> {
  try {
    await apiRequest<void>(`/documents/${documentId}`, {
      method: 'DELETE',
      tenantId: user.tenantId,
      userId: user.id,
      roles: user.roles,
    })
  } catch (error) {
    const conflict = parseDeleteDocumentConflict(error)
    if (conflict) {
      throw new DocumentDeleteConflictError(conflict)
    }
    throw error
  }
}

export async function retryDocumentIndexing(
  user: User,
  documentId: string,
  bucketId?: string,
): Promise<DocumentItem> {
  const query = bucketId ? `?bucket_id=${encodeURIComponent(bucketId)}` : ''
  const response = await apiRequest<CommitDocumentsDto>(
    `/documents/${documentId}/retry-indexing${query}`,
    {
      method: 'POST',
      tenantId: user.tenantId,
      userId: user.id,
      roles: user.roles,
    },
  )
  return mapDocument(response.documents[0])
}

export async function stageDocument(user: User, file: File): Promise<StagedDocumentItem> {
  const document = await apiRequest<StagedDocumentDto>('/documents/stage', {
    body: await file.arrayBuffer(),
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      ...fileNameHeaders(file.name),
    },
    json: false,
    method: 'POST',
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return mapStagedDocument(document)
}

export async function cancelStagedDocument(user: User, uploadId: string): Promise<void> {
  await apiRequest<void>(`/documents/stage/${uploadId}`, {
    method: 'DELETE',
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
}

export async function commitBucketDocuments(
  user: User,
  bucketId: string,
  payload: {
    stagedUploadIds: string[]
    existingDocumentIds: string[]
    removedDocumentIds: string[]
    visibility: DocumentItem['visibility']
  },
): Promise<DocumentItem[]> {
  const response = await apiRequest<CommitDocumentsDto>(
    `/buckets/${bucketId}/documents/-/commit`,
    {
      body: JSON.stringify({
        staged_upload_ids: payload.stagedUploadIds,
        existing_document_ids: payload.existingDocumentIds,
        removed_document_ids: payload.removedDocumentIds,
        visibility: payload.visibility,
        allowed_roles: [],
      }),
      method: 'POST',
      tenantId: user.tenantId,
      userId: user.id,
      roles: user.roles,
    },
  )
  return response.documents.map(mapDocument)
}

export async function commitPersonalDocuments(
  user: User,
  payload: {
    stagedUploadIds: string[]
    visibility: DocumentItem['visibility']
  },
): Promise<DocumentItem[]> {
  const response = await apiRequest<CommitDocumentsDto>('/documents/-/commit-personal', {
    body: JSON.stringify({
      staged_upload_ids: payload.stagedUploadIds,
      visibility: payload.visibility,
      allowed_roles: [],
    }),
    method: 'POST',
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return response.documents.map(mapDocument)
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

export class DocumentDeleteConflictError extends Error {
  readonly conflict: DeleteDocumentConflict

  constructor(conflict: DeleteDocumentConflict) {
    super('Document is used in buckets.')
    this.conflict = conflict
  }
}

function parseDeleteDocumentConflict(error: unknown): DeleteDocumentConflict | null {
  if (!(error instanceof Error)) {
    return null
  }
  try {
    const parsed = JSON.parse(error.message) as { detail?: DeleteDocumentConflict }
    if (parsed.detail?.reason === 'document_in_use') {
      return parsed.detail
    }
  } catch {
    return null
  }
  return null
}

function mapStagedDocument(document: StagedDocumentDto): StagedDocumentItem {
  return {
    id: document.id,
    fileName: document.original_file_name,
    sourceType: document.source_type,
    status: document.status,
    sizeBytes: document.size_bytes,
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
      ...fileNameHeaders(file.name),
    },
    json: false,
    method: 'POST',
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return mapDocument(document)
}

function fileNameHeaders(fileName: string): Record<string, string> {
  return {
    'X-File-Name': encodeURIComponent(fileName),
    'X-File-Name-Encoding': 'uri-component',
  }
}
