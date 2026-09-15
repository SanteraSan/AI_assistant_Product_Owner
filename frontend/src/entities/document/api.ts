import { apiRequest, apiRequestBlob, saveBlob } from '../../shared/api/httpClient'
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
  bucketId: string,
): Promise<DocumentItem[]> {
  const documents = await apiRequest<DocumentDto[]>(`/api/buckets/${bucketId}/documents`)
  return documents.map(mapDocument)
}

export async function downloadBucketDocument(
  bucketId: string,
  documentId: string,
  fallbackFileName: string,
): Promise<void> {
  const result = await apiRequestBlob(
    `/api/buckets/${bucketId}/documents/${documentId}/download`,
    { json: false },
  )
  saveBlob(result.blob, result.fileName || fallbackFileName)
}

export async function downloadBucketDocuments(
  bucketId: string,
  documentIds: string[],
  fallbackFileName: string,
): Promise<void> {
  if (documentIds.length === 1) {
    await downloadBucketDocument(bucketId, documentIds[0], fallbackFileName)
    return
  }
  const result = await apiRequestBlob(`/api/buckets/${bucketId}/documents/download`, {
    method: 'POST',
    body: JSON.stringify({ document_ids: documentIds }),
  })
  saveBlob(result.blob, result.fileName || fallbackFileName)
}

export async function fetchAvailableDocuments(): Promise<DocumentItem[]> {
  const documents = await apiRequest<DocumentDto[]>('/api/documents/available')
  return documents.map(mapDocument)
}

export async function fetchMyDocuments(): Promise<DocumentItem[]> {
  const documents = await apiRequest<DocumentDto[]>('/api/documents/my')
  return documents.map(mapDocument)
}

export async function addDocumentToBucket(
  bucketId: string,
  documentId: string,
): Promise<DocumentItem> {
  const document = await apiRequest<DocumentDto>(`/api/buckets/${bucketId}/documents/${documentId}`, {
    method: 'POST'
  })
  return mapDocument(document)
}

export async function removeDocumentFromBucket(
  bucketId: string,
  documentId: string,
): Promise<void> {
  await apiRequest<void>(`/api/buckets/${bucketId}/documents/${documentId}`, {
    method: 'DELETE'
  })
}

export type DeleteDocumentConflict = {
  reason: 'document_in_use'
  buckets: Array<{
    id: string
    name: string
  }>
}

export async function deleteDocument(documentId: string): Promise<void> {
  try {
    await apiRequest<void>(`/api/documents/${documentId}`, {
      method: 'DELETE'
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
  documentId: string,
  bucketId?: string,
): Promise<DocumentItem> {
  const query = bucketId ? `?bucket_id=${encodeURIComponent(bucketId)}` : ''
  const response = await apiRequest<CommitDocumentsDto>(
    `/api/documents/${documentId}/retry-indexing${query}`,
    {
      method: 'POST'
  },
  )
  return mapDocument(response.documents[0])
}

export async function stageDocument(file: File): Promise<StagedDocumentItem> {
  const document = await apiRequest<StagedDocumentDto>('/api/documents/stage', {
    body: await file.arrayBuffer(),
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      ...fileNameHeaders(file.name)
  },
    json: false,
    method: 'POST'
  })
  return mapStagedDocument(document)
}

export async function cancelStagedDocument(uploadId: string): Promise<void> {
  await apiRequest<void>(`/api/documents/stage/${uploadId}`, {
    method: 'DELETE'
  })
}

export async function commitBucketDocuments(
  bucketId: string,
  payload: {
    stagedUploadIds: string[]
    existingDocumentIds: string[]
    removedDocumentIds: string[]
    visibility: DocumentItem['visibility']
  },
): Promise<DocumentItem[]> {
  const response = await apiRequest<CommitDocumentsDto>(
    `/api/buckets/${bucketId}/documents/-/commit`,
    {
      body: JSON.stringify({
        staged_upload_ids: payload.stagedUploadIds,
        existing_document_ids: payload.existingDocumentIds,
        removed_document_ids: payload.removedDocumentIds,
        visibility: payload.visibility,
        allowed_roles: []
  }),
      method: 'POST'
  },
  )
  return response.documents.map(mapDocument)
}

export async function commitPersonalDocuments(
  payload: {
    stagedUploadIds: string[]
    visibility: DocumentItem['visibility']
  },
): Promise<DocumentItem[]> {
  const response = await apiRequest<CommitDocumentsDto>('/api/documents/-/commit-personal', {
    body: JSON.stringify({
      staged_upload_ids: payload.stagedUploadIds,
      visibility: payload.visibility,
      allowed_roles: []
  }),
    method: 'POST'
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
    uploadedAt: new Date(document.created_at).toLocaleString('ru-RU')
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
    uploadedAt: new Date(document.created_at).toLocaleString('ru-RU')
  }
}

export async function uploadDocument(
  bucketId: string,
  file: File,
  visibility: DocumentItem['visibility'] = 'private',
): Promise<DocumentItem> {
  const document = await apiRequest<DocumentDto>(`/api/buckets/${bucketId}/documents/upload`, {
    body: await file.arrayBuffer(),
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      'X-Document-Visibility': visibility,
      ...fileNameHeaders(file.name)
  },
    json: false,
    method: 'POST'
  })
  return mapDocument(document)
}

function fileNameHeaders(fileName: string): Record<string, string> {
  return {
    'X-File-Name': encodeURIComponent(fileName),
    'X-File-Name-Encoding': 'uri-component'
  }
}
