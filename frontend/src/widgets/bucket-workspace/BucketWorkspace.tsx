import { FileText, Folder, Pencil, Plus, Upload } from 'lucide-react'
import type { ReactNode } from 'react'
import { useRef, useState } from 'react'
import type { Bucket } from '../../entities/bucket/model'
import type { DocumentItem, StagedDocumentItem } from '../../entities/document/model'
import { Badge, Button, Card, Modal } from '../../shared/ui'

type BucketWorkspaceProps = {
  buckets: Bucket[]
  availableDocuments: DocumentItem[]
  canMutateDocuments: boolean
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
  onInspectBucket: (bucketId: string) => void
  onSelectBucket: (bucketId: string) => void
  onStageDocument: (file: File) => Promise<StagedDocumentItem>
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
  documents,
  onCancelStagedDocument,
  onCommitChanges,
  onCreateBucket,
  onInspectBucket,
  onSelectBucket,
  onStageDocument,
}: BucketWorkspaceProps) {
  const [openedBucket, setOpenedBucket] = useState<Bucket | null>(null)
  const [existingDraftIds, setExistingDraftIds] = useState<string[]>([])
  const [removedDocumentIds, setRemovedDocumentIds] = useState<string[]>([])
  const [stagedUploads, setStagedUploads] = useState<StagedDocumentItem[]>([])
  const [isSaving, setIsSaving] = useState(false)
  const [draftError, setDraftError] = useState<string | null>(null)
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
                <Button variant="ghost">
                  <Pencil size={16} />
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
                          <Button
                            disabled={!canMutateDocuments}
                            onClick={() => handleDraftRemoveDocument(document.id)}
                            variant="ghost"
                          >
                            Убрать
                          </Button>
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
                          <Button
                            disabled={!canMutateDocuments}
                            onClick={() => handleDraftExistingDocument(document.id)}
                            variant="ghost"
                          >
                            Добавить
                          </Button>
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
    </main>
  )
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
