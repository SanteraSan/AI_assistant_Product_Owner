import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { createBucket, deleteBucket, fetchBuckets, updateBucket } from '../../entities/bucket/api'
import {
  cancelStagedDocument,
  commitBucketDocuments,
  deleteDocument,
  DocumentDeleteConflictError,
  downloadBucketDocuments,
  fetchAvailableDocuments,
  fetchBucketDocuments,
  retryDocumentIndexing,
  stageDocument,
} from '../../entities/document/api'
import type { DocumentItem } from '../../entities/document/model'

type UseBucketLibraryOptions = {
  isAuthenticated: boolean
  roles?: string[]
  selectedBucketId: string
  selectBucket: (bucketId: string) => void
  tenantId?: string
  userId?: string
}

export function useBucketLibrary({
  isAuthenticated,
  roles,
  selectedBucketId,
  selectBucket,
  tenantId,
  userId,
}: UseBucketLibraryOptions) {
  const queryClient = useQueryClient()
  const [inspectedBucketId, setInspectedBucketId] = useState('')
  const bucketsQuery = useQuery({
    enabled: isAuthenticated,
    queryKey: ['buckets', tenantId],
    queryFn: () => fetchBuckets(),
    retry: false,
  })
  const hasBackendBuckets = Boolean(bucketsQuery.data?.length)
  const buckets = bucketsQuery.data ?? []
  const documentsQuery = useQuery({
    enabled: isAuthenticated && hasBackendBuckets && Boolean(inspectedBucketId),
    queryKey: ['bucket-documents', tenantId, inspectedBucketId],
    queryFn: () => fetchBucketDocuments(inspectedBucketId),
    refetchInterval: (query) =>
      query.state.data?.some((document) => document.status === 'indexing')
        ? 3000
        : false,
    retry: false,
  })
  const documents = useMemo(
    () => (hasBackendBuckets ? (documentsQuery.data ?? []) : []),
    [documentsQuery.data, hasBackendBuckets],
  )
  const availableDocumentsQuery = useQuery({
    enabled: isAuthenticated && hasBackendBuckets,
    queryKey: ['documents-available', tenantId, userId, roles],
    queryFn: () => fetchAvailableDocuments(),
    refetchInterval: (query) =>
      query.state.data?.some((document) => document.status === 'indexing') ? 3000 : false,
    retry: false,
  })
  const availableDocuments = useMemo(
    () => (hasBackendBuckets ? (availableDocumentsQuery.data ?? []) : []),
    [availableDocumentsQuery.data, hasBackendBuckets],
  )
  const stageDocumentMutation = useMutation({
    mutationFn: (file: File) => stageDocument(file),
  })
  const cancelStagedDocumentMutation = useMutation({
    mutationFn: (uploadId: string) => cancelStagedDocument(uploadId),
  })
  const commitBucketDocumentsMutation = useMutation({
    mutationFn: ({
      bucketId,
      existingDocumentIds,
      removedDocumentIds,
      stagedUploadIds,
    }: {
      bucketId: string
      existingDocumentIds: string[]
      removedDocumentIds: string[]
      stagedUploadIds: string[]
    }) =>
      commitBucketDocuments(bucketId, {
        existingDocumentIds,
        removedDocumentIds,
        stagedUploadIds,
        visibility: 'private',
      }),
    onSuccess: (committedDocuments, variables) => {
      queryClient.setQueryData(
        ['bucket-documents', tenantId, variables.bucketId],
        (current: typeof committedDocuments | undefined) => {
          const remainingDocuments = (current ?? []).filter(
            (document) => !variables.removedDocumentIds.includes(document.id),
          )
          const committedById = new Map(committedDocuments.map((document) => [document.id, document]))
          const mergedDocuments = remainingDocuments.map((document) =>
            committedById.get(document.id) ?? document,
          )
          for (const document of committedDocuments) {
            if (!mergedDocuments.some((existingDocument) => existingDocument.id === document.id)) {
              mergedDocuments.push(document)
            }
          }
          return mergedDocuments
        },
      )
      void queryClient.invalidateQueries({ queryKey: ['bucket-documents'] })
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
    },
  })
  const deleteDocumentMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(documentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
      void queryClient.invalidateQueries({ queryKey: ['bucket-documents'] })
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
    },
  })
  const retryDocumentIndexingMutation = useMutation({
    mutationFn: ({
      bucketId,
      documentId,
    }: {
      documentId: string
      bucketId?: string
    }) => retryDocumentIndexing(documentId, bucketId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
      void queryClient.invalidateQueries({ queryKey: ['bucket-documents'] })
    },
  })
  const createBucketMutation = useMutation({
    mutationFn: () =>
      createBucket({
        name: `Личная база знаний ${new Date().toLocaleTimeString('ru-RU')}`,
        description: 'Персональный bucket для документов, загруженных через UI.',
      }),
    onSuccess: (bucket) => {
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
      selectBucket(bucket.id)
    },
  })
  const updateBucketMutation = useMutation({
    mutationFn: ({
      bucketId,
      description,
      name,
    }: {
      bucketId: string
      description: string
      name: string
    }) => updateBucket(bucketId, { name, description }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
    },
  })
  const deleteBucketMutation = useMutation({
    mutationFn: (bucketId: string) => deleteBucket(bucketId),
    onSuccess: (_result, bucketId) => {
      if (selectedBucketId === bucketId) {
        selectBucket('')
      }
      if (inspectedBucketId === bucketId) {
        setInspectedBucketId('')
      }
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
      void queryClient.invalidateQueries({ queryKey: ['bucket-documents'] })
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
    },
  })

  async function deleteLibraryDocument(documentId: string) {
    try {
      await deleteDocumentMutation.mutateAsync(documentId)
    } catch (error) {
      if (error instanceof DocumentDeleteConflictError) {
        const bucketNames = error.conflict.buckets.map((bucket) => bucket.name).join(', ')
        throw new Error(
          `Этот файл ещё используется в bucket: ${bucketNames}. Сначала уберите его из этих bucket.`,
          { cause: error },
        )
      }
      throw error
    }
  }

  return {
    availableDocuments,
    buckets,
    documents,
    hasBackendBuckets,
    setInspectedBucketId,
    stageDocument: (file: File) => stageDocumentMutation.mutateAsync(file),
    cancelStagedDocument: (uploadId: string) => cancelStagedDocumentMutation.mutateAsync(uploadId),
    commitBucketChanges: (bucketId: string, changes: {
      stagedUploadIds: string[]
      existingDocumentIds: string[]
      removedDocumentIds: string[]
    }) => commitBucketDocumentsMutation.mutateAsync({ bucketId, ...changes }),
    createBucket: () => createBucketMutation.mutate(),
    deleteBucket: (bucketId: string) => deleteBucketMutation.mutateAsync(bucketId),
    deleteLibraryDocument,
    downloadDocuments: downloadBucketDocuments,
    retryIndexing: (documentId: string, bucketId?: string) =>
      retryDocumentIndexingMutation.mutateAsync({ documentId, bucketId }),
    updateBucket: (bucketId: string, payload: { name: string; description: string }) =>
      updateBucketMutation.mutateAsync({ bucketId, ...payload }),
  }
}

export type { DocumentItem }
