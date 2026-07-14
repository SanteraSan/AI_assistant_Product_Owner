import { FileText, Folder, Pencil, Plus, RotateCcw, Trash2, Upload } from 'lucide-react'
import type { ReactNode } from 'react'
import { useRef, useState } from 'react'
import type { Bucket } from '../../entities/bucket/model'
import type { DocumentItem, StagedDocumentItem } from '../../entities/document/model'
import { Badge, Button, Card, Modal } from '../../shared/ui'

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
  onInspectBucket: (bucketId: string) => void
  onRetryIndexing: (documentId: string, bucketId?: string) => Promise<void>
  onSelectBucket: (bucketId: string) => void
  onStageDocument: (file: File) => Promise<StagedDocumentItem>
  onUpdateBucket: (
    bucketId: string,
    payload: { name: string; description: string },
  ) => Promise<void>
}

const statusTone = {
  ready: 'success',
  indexing: 'warning',
  error: 'danger',
} as const

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
          <Card className="p-5" key={bucket.id}>
            <div className="flex items-start justify-between gap-4">
              <div className="flex gap-4">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
                  <Folder size={22} />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-slate-950">{bucket.name}</h3>
                  <p className="mt-1 text-sm leading-6 text-slate-500">{bucket.description}</p>
                </div>
              </div>
              <Badge tone={statusTone[bucket.status]}>{bucket.status}</Badge>
            </div>

            <div className="mt-5 flex items-center justify-between border-t border-slate-100 pt-4">
              <p className="text-sm text-slate-500">{bucket.documentCount} documents</p>
              <div className="flex gap-2">
                <Button onClick={() => onSelectBucket(bucket.id)} variant="ghost">
                  Выбрать
                </Button>
                <Button onClick={() => openDocuments(bucket)} variant="secondary">
                  <FileText size={16} />
                  Документы
                </Button>
                <Button
                  disabled={!canMutateDocuments}
                  onClick={() => {
                    setBucketActionError(null)
                    setEditName(bucket.name)
                    setEditDescription(bucket.description)
                    setBucketToEdit(bucket)
                  }}
                  variant="ghost"
                >
                  <Pencil size={16} />
                </Button>
                <Button
                  className="text-red-600 hover:bg-red-50 hover:text-red-700"
                  disabled={!canMutateDocuments}
                  onClick={() => {
                    setBucketActionError(null)
                    setBucketToDelete(bucket)
                  }}
                  variant="ghost"
                >
                  <Trash2 size={16} />
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Modal
        bodyClassName="flex flex-1 flex-col overflow-hidden p-0"
        isOpen={openedBucket !== null}
        onClose={handleClose}
        size="lg"
        title={openedBucket ? `Документы: ${openedBucket.name}` : 'Документы'}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-100 px-6 py-4">
          <p className="text-sm text-slate-500">
            Bucket хранит ссылки на документы. Доступ всё равно проверяется по owner/role/tenant.
          </p>
          <input
            className="hidden"
            onChange={(event) => handleUpload(event.target.files?.[0])}
            ref={uploadInputRef}
            type="file"
          />
          <Button
            disabled={!canMutateDocuments}
            onClick={() => uploadInputRef.current?.click()}
            variant="primary"
          >
            <Upload size={18} />
            Загрузить документ
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden px-6 py-4">
          {!canMutateDocuments ? (
            <p className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Сейчас открыт demo bucket. Создай реальный bucket в БД, чтобы загружать и привязывать документы.
            </p>
          ) : null}
          {draftError ? (
            <p className="mb-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {draftError}
            </p>
          ) : null}

          <div className="grid h-full min-h-0 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-4">
            <section className="flex min-h-0 flex-col overflow-hidden rounded-3xl border border-slate-100 bg-slate-50/60 p-4">
              <h3 className="mb-3 shrink-0 text-sm font-semibold uppercase tracking-wide text-slate-500">
                В этом bucket
                {bucketDocumentCount > 0 ? (
                  <span className="ml-2 text-slate-400">{bucketDocumentCount}</span>
                ) : null}
              </h3>
              <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
                {visibleDocuments.length === 0 &&
                draftedExistingDocuments.length === 0 &&
                stagedUploads.length === 0 ? (
                  <p className="rounded-2xl border border-dashed border-slate-200 bg-white p-4 text-sm text-slate-500">
                    Документов пока нет. Можно загрузить новый или добавить доступный из библиотеки.
                  </p>
                ) : (
                  <>
                    {visibleDocuments.map((document) => (
                      <DocumentRow
                        action={
                          <>
                            {document.status === 'index_failed' ? (
                              <Button
                                disabled={!canMutateDocuments || retryingDocumentId === document.id}
                                onClick={() => handleRetryIndexing(document.id, openedBucket?.id)}
                                variant="ghost"
                              >
                                <RotateCcw size={14} />
                                {retryingDocumentId === document.id ? 'Повтор...' : 'Повторить'}
                              </Button>
                            ) : null}
                            <Button
                              disabled={!canMutateDocuments}
                              onClick={() => handleDraftRemoveDocument(document.id)}
                              variant="ghost"
                            >
                              Убрать
                            </Button>
                          </>
                        }
                        document={document}
                        key={document.id}
                      />
                    ))}
                    {draftedExistingDocuments.map((document) => (
                      <DocumentRow
                        action={
                          <>
                            <Badge tone="warning">draft</Badge>
                            <Button
                              onClick={() => handleCancelDraftExistingDocument(document.id)}
                              variant="ghost"
                            >
                              Убрать
                            </Button>
                          </>
                        }
                        document={document}
                        key={`draft-existing-${document.id}`}
                      />
                    ))}
                    {stagedUploads.map((upload) => (
                      <StagedDocumentRow
                        action={
                          <Button onClick={() => handleCancelStagedUpload(upload.id)} variant="ghost">
                            Убрать
                          </Button>
                        }
                        document={upload}
                        key={upload.id}
                      />
                    ))}
                  </>
                )}
              </div>
            </section>

            <section className="flex min-h-0 flex-col overflow-hidden rounded-3xl border border-slate-100 bg-white p-4">
              <h3 className="mb-3 shrink-0 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Доступные документы
                {availableDocumentCount > 0 ? (
                  <span className="ml-2 text-slate-400">{availableDocumentCount}</span>
                ) : null}
              </h3>
              <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
                {addableDocuments.length === 0 ? (
                  <p className="rounded-2xl border border-dashed border-slate-200 p-4 text-sm text-slate-500">
                    Нет дополнительных документов, доступных для добавления.
                  </p>
                ) : (
                  addableDocuments.map((document) => (
                    <DocumentRow
                      action={
                        openedBucket ? (
                          <>
                            <Button
                              disabled={!canMutateDocuments}
                              onClick={() => handleDraftExistingDocument(document.id)}
                              variant="ghost"
                            >
                              Добавить
                            </Button>
                            {document.status === 'index_failed' ? (
                              <Button
                                disabled={!canMutateDocuments || retryingDocumentId === document.id}
                                onClick={() => handleRetryIndexing(document.id)}
                                variant="ghost"
                              >
                                <RotateCcw size={14} />
                                {retryingDocumentId === document.id ? 'Повтор...' : 'Повторить'}
                              </Button>
                            ) : null}
                            {canDeleteAvailableDocument(document, currentUserId) ? (
                              <Button
                                className="text-red-600 hover:bg-red-50 hover:text-red-700"
                                disabled={!canMutateDocuments}
                                onClick={() => setDocumentToDelete(document)}
                                variant="ghost"
                              >
                                Удалить
                              </Button>
                            ) : null}
                          </>
                        ) : null
                      }
                      document={document}
                      key={document.id}
                    />
                  ))
                )}
              </div>
            </section>
          </div>
        </div>

        <div className="flex shrink-0 items-center justify-between border-t border-slate-100 px-6 py-4">
          <p className="text-sm text-slate-500">
            {hasDraftChanges
              ? 'Есть несохранённые изменения. Индексация начнётся после сохранения.'
              : 'Изменений пока нет.'}
          </p>
          <Button disabled={!hasDraftChanges || isSaving} onClick={handleSaveChanges} variant="primary">
            {isSaving ? 'Сохраняем...' : 'Сохранить'}
          </Button>
        </div>
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
        <div className="space-y-4">
          <p className="text-sm leading-6 text-slate-600">
            Вы точно хотите удалить файл{' '}
            <span className="font-semibold text-slate-950">
              {documentToDelete?.fileName}
            </span>
            ? Это удалит его из личной библиотеки документов.
          </p>
          {deleteError ? (
            <p className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              {deleteError}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button
              disabled={isDeleting}
              onClick={() => {
                setDocumentToDelete(null)
                setDeleteError(null)
              }}
              variant="secondary"
            >
              Отмена
            </Button>
            <Button
              className="bg-red-600 text-white hover:bg-red-700"
              disabled={isDeleting}
              onClick={handleDeleteDocument}
              variant="primary"
            >
              {isDeleting ? 'Удаляем...' : 'Удалить'}
            </Button>
          </div>
        </div>
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
        <div className="space-y-4">
          <label className="block space-y-2 text-sm text-slate-700">
            <span>Название</span>
            <input
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-950 outline-none focus:border-slate-400"
              onChange={(event) => setEditName(event.target.value)}
              value={editName}
            />
          </label>
          <label className="block space-y-2 text-sm text-slate-700">
            <span>Описание</span>
            <textarea
              className="min-h-24 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-950 outline-none focus:border-slate-400"
              onChange={(event) => setEditDescription(event.target.value)}
              value={editDescription}
            />
          </label>
          {bucketActionError && bucketToEdit ? (
            <p className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {bucketActionError}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button
              disabled={isBucketActionSaving}
              onClick={() => setBucketToEdit(null)}
              variant="secondary"
            >
              Отмена
            </Button>
            <Button disabled={isBucketActionSaving} onClick={handleSaveBucketEdit} variant="primary">
              {isBucketActionSaving ? 'Сохраняем...' : 'Сохранить'}
            </Button>
          </div>
        </div>
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
        <div className="space-y-4">
          <p className="text-sm leading-6 text-slate-600">
            Bucket{' '}
            <span className="font-semibold text-slate-950">{bucketToDelete?.name}</span> будет
            удалён. Документы из него останутся в списке «Доступные документы».
          </p>
          {bucketActionError && bucketToDelete ? (
            <p className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {bucketActionError}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button
              disabled={isBucketActionSaving}
              onClick={() => setBucketToDelete(null)}
              variant="secondary"
            >
              Отмена
            </Button>
            <Button
              className="bg-red-600 text-white hover:bg-red-700"
              disabled={isBucketActionSaving}
              onClick={handleDeleteBucket}
              variant="primary"
            >
              {isBucketActionSaving ? 'Удаляем...' : 'Удалить'}
            </Button>
          </div>
        </div>
      </Modal>
    </main>
  )
}

function canDeleteAvailableDocument(document: DocumentItem, currentUserId: string): boolean {
  return document.ownerUserId === currentUserId && document.visibility === 'private'
}

function StagedDocumentRow({
  action,
  document,
}: {
  action?: ReactNode
  document: StagedDocumentItem
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-4">
      <div>
        <p className="font-medium text-slate-950">{document.fileName}</p>
        <p className="mt-1 text-sm text-slate-500">
          {document.sourceType} · staged · {document.uploadedAt}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Badge tone="warning">{document.status}</Badge>
        {action}
      </div>
    </div>
  )
}

function DocumentRow({
  action,
  document,
}: {
  action?: ReactNode
  document: DocumentItem
}) {
  const isIndexing = document.status === 'indexing'
  const isUploadedOnly = document.status === 'uploaded'
  return (
    <div className="rounded-2xl border border-slate-200 p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="font-medium text-slate-950">{document.fileName}</p>
          <p className="mt-1 text-sm text-slate-500">
            {document.sourceType} · {document.visibility} · {document.uploadedAt}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={statusToneForDocument(document.status)}>{document.status}</Badge>
          {action}
        </div>
      </div>
      {isIndexing ? (
        <div className="mt-3">
          <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full w-1/2 animate-pulse rounded-full bg-amber-400" />
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Документ сохраняется в Qdrant. Статус обновляется автоматически.
          </p>
        </div>
      ) : null}
      {isUploadedOnly ? (
        <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700">
          Документ сохранён в библиотеке, но для него ещё не создана задача индексации.
        </p>
      ) : null}
    </div>
  )
}

function statusToneForDocument(status: DocumentItem['status']) {
  if (status === 'indexed') {
    return 'success'
  }
  if (status === 'error' || status === 'index_failed') {
    return 'danger'
  }
  return 'warning'
}
