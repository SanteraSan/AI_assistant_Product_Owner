import { Plus } from 'lucide-react'
import { useRef, useState } from 'react'
import type { Bucket } from '../../entities/bucket/model'
import type { DocumentItem, StagedDocumentItem } from '../../entities/document/model'
import { Button, ConfirmDialog, Modal } from '../../shared/ui'
import { BucketCard } from './BucketCard'
import { BucketDocumentsPanel } from './BucketDocumentsPanel'
import { DeleteDocumentDialog } from './DeleteDocumentDialog'
import { DownloadPicker } from './DownloadPicker'
import { EditBucketForm } from './EditBucketForm'

type BucketWorkspaceProps = {
  buckets: Bucket[]
  availableDocuments: DocumentItem[]
  canMutateDocuments: boolean
  currentUserId: string
  documents: DocumentItem[]
  onCancelStagedDocument: (uploadId: string) => Promise<void>
  onCommitChanges: (
    bucketId: string,
    changes: {
      stagedUploadIds: string[]
      existingDocumentIds: string[]
      removedDocumentIds: string[]
    },
  ) => Promise<void>
  onCreateBucket: () => void
  onDeleteBucket: (bucketId: string) => Promise<void>
  onDeleteDocument: (documentId: string) => Promise<void>
  onDownloadDocuments: (
    bucketId: string,
    documentIds: string[],
    fallbackFileName: string,
  ) => Promise<void>
  onInspectBucket: (bucketId: string) => void
  onRetryIndexing: (documentId: string, bucketId?: string) => Promise<void>
  onSelectBucket: (bucketId: string) => void
  onStageDocument: (file: File) => Promise<StagedDocumentItem>
  onUpdateBucket: (
    bucketId: string,
    payload: { name: string; description: string },
  ) => Promise<void>
}

export function BucketWorkspace({
  availableDocuments,
  buckets,
  canMutateDocuments,
  currentUserId,
  documents,
  onCancelStagedDocument,
  onCommitChanges,
  onCreateBucket,
  onDeleteBucket,
  onDeleteDocument,
  onDownloadDocuments,
  onInspectBucket,
  onRetryIndexing,
  onSelectBucket,
  onStageDocument,
  onUpdateBucket,
}: BucketWorkspaceProps) {
  const [openedBucket, setOpenedBucket] = useState<Bucket | null>(null)
  const [bucketToEdit, setBucketToEdit] = useState<Bucket | null>(null)
  const [bucketToDelete, setBucketToDelete] = useState<Bucket | null>(null)
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [existingDraftIds, setExistingDraftIds] = useState<string[]>([])
  const [removedDocumentIds, setRemovedDocumentIds] = useState<string[]>([])
  const [stagedUploads, setStagedUploads] = useState<StagedDocumentItem[]>([])
  const [isSaving, setIsSaving] = useState(false)
  const [isBucketActionSaving, setIsBucketActionSaving] = useState(false)
  const [retryingDocumentId, setRetryingDocumentId] = useState<string | null>(null)
  const [documentToDelete, setDocumentToDelete] = useState<DocumentItem | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [downloadPickerOpen, setDownloadPickerOpen] = useState(false)
  const [selectedDownloadIds, setSelectedDownloadIds] = useState<string[]>([])
  const [isDownloading, setIsDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [draftError, setDraftError] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [bucketActionError, setBucketActionError] = useState<string | null>(null)
  const uploadInputRef = useRef<HTMLInputElement | null>(null)
  const documentsInBucket = new Set(
    documents
      .filter((document) => !removedDocumentIds.includes(document.id))
      .map((document) => document.id),
  )
  const existingDraftIdSet = new Set(existingDraftIds)
  const addableDocuments = availableDocuments.filter(
    (document) => !documentsInBucket.has(document.id) && !existingDraftIdSet.has(document.id),
  )
  const visibleDocuments = documents.filter((document) => !removedDocumentIds.includes(document.id))
  const draftedExistingDocuments = availableDocuments.filter((document) =>
    existingDraftIdSet.has(document.id),
  )
  const bucketDocumentCount = visibleDocuments.length + draftedExistingDocuments.length + stagedUploads.length
  const availableDocumentCount = addableDocuments.length
  const hasDraftChanges =
    stagedUploads.length > 0 || existingDraftIds.length > 0 || removedDocumentIds.length > 0

  function openDocuments(bucket: Bucket) {
    onInspectBucket(bucket.id)
    resetDraft()
    setOpenedBucket(bucket)
  }

  async function handleUpload(file: File | undefined) {
    if (!file || openedBucket === null || !canMutateDocuments) {
      return
    }
    setDraftError(null)
    try {
      const stagedDocument = await onStageDocument(file)
      setStagedUploads((current) => [...current, stagedDocument])
    } catch (error) {
      setDraftError(error instanceof Error ? error.message : 'Не удалось загрузить файл в staging.')
    } finally {
      if (uploadInputRef.current) {
        uploadInputRef.current.value = ''
      }
    }
  }

  function handleClose() {
    if (hasDraftChanges && !window.confirm('Закрыть без сохранения изменений bucket?')) {
      return
    }
    resetDraft()
    closeDownloadPicker()
    setOpenedBucket(null)
  }

  function handleDraftExistingDocument(documentId: string) {
    setExistingDraftIds((current) =>
      current.includes(documentId) ? current : [...current, documentId],
    )
  }

  function handleCancelDraftExistingDocument(documentId: string) {
    setExistingDraftIds((current) => current.filter((currentDocumentId) => currentDocumentId !== documentId))
  }

  function handleDraftRemoveDocument(documentId: string) {
    setRemovedDocumentIds((current) =>
      current.includes(documentId) ? current : [...current, documentId],
    )
  }

  async function handleCancelStagedUpload(uploadId: string) {
    setDraftError(null)
    try {
      await onCancelStagedDocument(uploadId)
      setStagedUploads((current) => current.filter((upload) => upload.id !== uploadId))
    } catch (error) {
      setDraftError(error instanceof Error ? error.message : 'Не удалось отменить staged upload.')
    }
  }

  async function handleSaveChanges() {
    if (openedBucket === null || !hasDraftChanges) {
      return
    }
    setIsSaving(true)
    setDraftError(null)
    try {
      await onCommitChanges(openedBucket.id, {
        stagedUploadIds: stagedUploads.map((upload) => upload.id),
        existingDocumentIds: existingDraftIds,
        removedDocumentIds,
      })
      resetDraft()
    } catch (error) {
      setDraftError(error instanceof Error ? error.message : 'Не удалось сохранить изменения bucket.')
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDeleteDocument() {
    if (documentToDelete === null) {
      return
    }
    setIsDeleting(true)
    setDeleteError(null)
    setDraftError(null)
    try {
      await onDeleteDocument(documentToDelete.id)
      setDocumentToDelete(null)
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : 'Не удалось удалить документ.')
    } finally {
      setIsDeleting(false)
    }
  }

  async function handleRetryIndexing(documentId: string, bucketId?: string) {
    setRetryingDocumentId(documentId)
    setDraftError(null)
    try {
      await onRetryIndexing(documentId, bucketId)
    } catch (error) {
      setDraftError(error instanceof Error ? error.message : 'Не удалось повторить индексацию.')
    } finally {
      setRetryingDocumentId(null)
    }
  }

  async function handleSaveBucketEdit() {
    if (bucketToEdit === null) {
      return
    }
    const nextName = editName.trim()
    if (!nextName) {
      setBucketActionError('Название bucket не может быть пустым.')
      return
    }
    setIsBucketActionSaving(true)
    setBucketActionError(null)
    try {
      await onUpdateBucket(bucketToEdit.id, {
        name: nextName,
        description: editDescription.trim(),
      })
      if (openedBucket?.id === bucketToEdit.id) {
        setOpenedBucket({
          ...openedBucket,
          name: nextName,
          description: editDescription.trim(),
        })
      }
      setBucketToEdit(null)
    } catch (error) {
      setBucketActionError(error instanceof Error ? error.message : 'Не удалось обновить bucket.')
    } finally {
      setIsBucketActionSaving(false)
    }
  }

  async function handleDeleteBucket() {
    if (bucketToDelete === null) {
      return
    }
    setIsBucketActionSaving(true)
    setBucketActionError(null)
    try {
      await onDeleteBucket(bucketToDelete.id)
      if (openedBucket?.id === bucketToDelete.id) {
        resetDraft()
        closeDownloadPicker()
        setOpenedBucket(null)
      }
      setBucketToDelete(null)
    } catch (error) {
      setBucketActionError(error instanceof Error ? error.message : 'Не удалось удалить bucket.')
    } finally {
      setIsBucketActionSaving(false)
    }
  }

  function resetDraft() {
    setExistingDraftIds([])
    setRemovedDocumentIds([])
    setStagedUploads([])
    setDraftError(null)
  }

  function closeDownloadPicker() {
    setDownloadPickerOpen(false)
    setSelectedDownloadIds([])
    setDownloadError(null)
  }

  function openDownloadPicker() {
    setSelectedDownloadIds(visibleDocuments.map((document) => document.id))
    setDownloadError(null)
    setDownloadPickerOpen(true)
  }

  function toggleDownloadId(documentId: string) {
    setSelectedDownloadIds((current) =>
      current.includes(documentId)
        ? current.filter((item) => item !== documentId)
        : [...current, documentId],
    )
  }

  function toggleSelectAllDownloads() {
    const allIds = visibleDocuments.map((document) => document.id)
    setSelectedDownloadIds((current) =>
      current.length === allIds.length ? [] : allIds,
    )
  }

  async function handleDownload(documentIds: string[]) {
    if (openedBucket === null || documentIds.length === 0) {
      return
    }
    const fallbackFileName =
      documentIds.length === 1
        ? (visibleDocuments.find((document) => document.id === documentIds[0])?.fileName ??
          'document')
        : `${openedBucket.name.trim().toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-') || 'bucket'}-documents.zip`
    setIsDownloading(true)
    setDownloadError(null)
    try {
      await onDownloadDocuments(openedBucket.id, documentIds, fallbackFileName)
      closeDownloadPicker()
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : 'Не удалось скачать документы.')
    } finally {
      setIsDownloading(false)
    }
  }

  return (
    <main className="min-h-0 flex-1 overflow-y-auto bg-slate-50 p-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-500">Knowledge buckets</p>
          <h2 className="mt-1 text-3xl font-semibold text-slate-950">Папки с документами</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            Здесь будет управление buckets: название, описание, документы и статус индексации.
          </p>
        </div>
        <Button onClick={onCreateBucket} variant="primary">
          <Plus size={18} />
          Создать bucket
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {buckets.map((bucket) => (
          <BucketCard
            bucket={bucket}
            canMutateDocuments={canMutateDocuments}
            key={bucket.id}
            onDelete={(item) => {
              setBucketActionError(null)
              setBucketToDelete(item)
            }}
            onEdit={(item) => {
              setBucketActionError(null)
              setEditName(item.name)
              setEditDescription(item.description)
              setBucketToEdit(item)
            }}
            onOpenDocuments={openDocuments}
            onSelect={onSelectBucket}
          />
        ))}
      </div>

      <Modal
        bodyClassName="flex flex-1 flex-col overflow-hidden p-0"
        isOpen={openedBucket !== null}
        onClose={handleClose}
        size="lg"
        title={openedBucket ? `Документы: ${openedBucket.name}` : 'Документы'}
      >
        <BucketDocumentsPanel
          addableDocuments={addableDocuments}
          availableDocumentCount={availableDocumentCount}
          bucketDocumentCount={bucketDocumentCount}
          canMutateDocuments={canMutateDocuments}
          currentUserId={currentUserId}
          downloadError={downloadError}
          downloadPickerOpen={downloadPickerOpen}
          draftError={draftError}
          draftedExistingDocuments={draftedExistingDocuments}
          hasDraftChanges={hasDraftChanges}
          isDownloading={isDownloading}
          isSaving={isSaving}
          onAddExisting={handleDraftExistingDocument}
          onAskDelete={setDocumentToDelete}
          onCancelDraftExisting={handleCancelDraftExistingDocument}
          onCancelStaged={(uploadId) => {
            void handleCancelStagedUpload(uploadId)
          }}
          onDownloadOne={(documentId) => {
            void handleDownload([documentId])
          }}
          onOpenDownloadPicker={openDownloadPicker}
          onRemove={handleDraftRemoveDocument}
          onRetry={(documentId, bucketId) => {
            void handleRetryIndexing(documentId, bucketId)
          }}
          onSave={() => {
            void handleSaveChanges()
          }}
          onUpload={handleUpload}
          openedBucketId={openedBucket?.id}
          retryingDocumentId={retryingDocumentId}
          stagedUploads={stagedUploads}
          uploadInputRef={uploadInputRef}
          visibleDocuments={visibleDocuments}
        />
      </Modal>

      <Modal
        bodyClassName="flex min-h-0 flex-1 flex-col overflow-hidden p-0"
        className="h-[80vh]"
        isOpen={downloadPickerOpen}
        nested
        onClose={() => {
          if (!isDownloading) {
            closeDownloadPicker()
          }
        }}
        title="Скачать документы"
      >
        <DownloadPicker
          documents={visibleDocuments}
          error={downloadError}
          isDownloading={isDownloading}
          onCancel={closeDownloadPicker}
          onDownload={() => void handleDownload(selectedDownloadIds)}
          onToggle={toggleDownloadId}
          onToggleAll={toggleSelectAllDownloads}
          selectedIds={selectedDownloadIds}
        />
      </Modal>

      <Modal
        isOpen={documentToDelete !== null}
        onClose={() => {
          if (!isDeleting) {
            setDocumentToDelete(null)
            setDeleteError(null)
          }
        }}
        title="Удалить файл?"
      >
        <DeleteDocumentDialog
          error={deleteError}
          fileName={documentToDelete?.fileName ?? ''}
          isDeleting={isDeleting}
          onCancel={() => {
            setDocumentToDelete(null)
            setDeleteError(null)
          }}
          onConfirm={() => {
            void handleDeleteDocument()
          }}
        />
      </Modal>

      <Modal
        isOpen={bucketToEdit !== null}
        onClose={() => {
          if (!isBucketActionSaving) {
            setBucketToEdit(null)
            setBucketActionError(null)
          }
        }}
        title="Редактировать bucket"
      >
        <EditBucketForm
          description={editDescription}
          error={bucketActionError && bucketToEdit ? bucketActionError : null}
          name={editName}
          onCancel={() => setBucketToEdit(null)}
          onChangeDescription={setEditDescription}
          onChangeName={setEditName}
          onSave={() => {
            void handleSaveBucketEdit()
          }}
          pending={isBucketActionSaving}
        />
      </Modal>

      <Modal
        isOpen={bucketToDelete !== null}
        onClose={() => {
          if (!isBucketActionSaving) {
            setBucketToDelete(null)
            setBucketActionError(null)
          }
        }}
        title="Удалить bucket?"
      >
        <ConfirmDialog
          confirmLabel="Удалить"
          danger
          error={bucketActionError && bucketToDelete ? bucketActionError : null}
          errorCompact
          onCancel={() => setBucketToDelete(null)}
          onConfirm={() => {
            void handleDeleteBucket()
          }}
          pending={isBucketActionSaving}
          pendingLabel="Удаляем..."
        >
          <p className="text-sm leading-6 text-slate-600">
            Bucket{' '}
            <span className="font-semibold text-slate-950">{bucketToDelete?.name}</span> будет
            удалён. Документы из него останутся в списке «Доступные документы».
          </p>
        </ConfirmDialog>
      </Modal>
    </main>
  )
}
