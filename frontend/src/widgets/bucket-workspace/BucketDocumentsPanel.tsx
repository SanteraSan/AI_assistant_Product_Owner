import type { RefObject } from 'react'
import { Download, Upload } from 'lucide-react'
import type { DocumentItem, StagedDocumentItem } from '../../entities/document/model'
import { Badge, Button, EmptyState, Notice } from '../../shared/ui'
import { DocumentListSection } from './DocumentListSection'
import { DocumentRow } from './DocumentRow'
import { RetryIndexingButton } from './RetryIndexingButton'
import { StagedDocumentRow } from './StagedDocumentRow'
import { canDeleteAvailableDocument } from './documentRules'

type BucketDocumentsPanelProps = {
  addableDocuments: DocumentItem[]
  availableDocumentCount: number
  bucketDocumentCount: number
  canMutateDocuments: boolean
  currentUserId: string
  downloadError: string | null
  downloadPickerOpen: boolean
  draftError: string | null
  draftedExistingDocuments: DocumentItem[]
  hasDraftChanges: boolean
  isDownloading: boolean
  isSaving: boolean
  onAddExisting: (documentId: string) => void
  onAskDelete: (document: DocumentItem) => void
  onCancelDraftExisting: (documentId: string) => void
  onCancelStaged: (uploadId: string) => void
  onDownloadOne: (documentId: string) => void
  onOpenDownloadPicker: () => void
  onRemove: (documentId: string) => void
  onRetry: (documentId: string, bucketId?: string) => void
  onSave: () => void
  onUpload: (file: File | undefined) => void
  openedBucketId?: string
  retryingDocumentId: string | null
  stagedUploads: StagedDocumentItem[]
  uploadInputRef: RefObject<HTMLInputElement | null>
  visibleDocuments: DocumentItem[]
}

export function BucketDocumentsPanel({
  addableDocuments,
  availableDocumentCount,
  bucketDocumentCount,
  canMutateDocuments,
  currentUserId,
  downloadError,
  downloadPickerOpen,
  draftError,
  draftedExistingDocuments,
  hasDraftChanges,
  isDownloading,
  isSaving,
  onAddExisting,
  onAskDelete,
  onCancelDraftExisting,
  onCancelStaged,
  onDownloadOne,
  onOpenDownloadPicker,
  onRemove,
  onRetry,
  onSave,
  onUpload,
  openedBucketId,
  retryingDocumentId,
  stagedUploads,
  uploadInputRef,
  visibleDocuments,
}: BucketDocumentsPanelProps) {
  const bucketIsEmpty = visibleDocuments.length === 0
    && draftedExistingDocuments.length === 0
    && stagedUploads.length === 0

  return (
    <>
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-100 px-6 py-4">
        <p className="text-sm text-slate-500">
          Bucket хранит ссылки на документы. Доступ всё равно проверяется по owner/role/tenant.
        </p>
        <input
          className="hidden"
          onChange={(event) => onUpload(event.target.files?.[0])}
          ref={uploadInputRef}
          type="file"
        />
        <div className="flex shrink-0 items-center gap-2">
          <Button
            disabled={visibleDocuments.length === 0 || isDownloading}
            onClick={onOpenDownloadPicker}
          >
            <Download size={18} />
            Скачать документы
          </Button>
          <Button
            disabled={!canMutateDocuments}
            onClick={() => uploadInputRef.current?.click()}
            variant="primary"
          >
            <Upload size={18} />
            Загрузить документ
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden px-6 py-4">
        {!canMutateDocuments ? (
          <Notice className="mb-4" tone="warning">
            Сейчас открыт demo bucket. Создай реальный bucket в БД, чтобы загружать и привязывать документы.
          </Notice>
        ) : null}
        {draftError ? <Notice className="mb-4">{draftError}</Notice> : null}
        {downloadError && !downloadPickerOpen ? (
          <Notice className="mb-4">{downloadError}</Notice>
        ) : null}

        <div className="grid h-full min-h-0 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-4">
          <DocumentListSection
            className="bg-slate-50/60"
            count={bucketDocumentCount}
            title="В этом bucket"
          >
            {bucketIsEmpty ? (
              <EmptyState filled>
                Документов пока нет. Можно загрузить новый или добавить доступный из библиотеки.
              </EmptyState>
            ) : (
              <>
                {visibleDocuments.map((document) => (
                  <DocumentRow
                    action={
                      <>
                        {document.status === 'index_failed' ? (
                          <RetryIndexingButton
                            disabled={!canMutateDocuments || retryingDocumentId === document.id}
                            onClick={() => onRetry(document.id, openedBucketId)}
                            pending={retryingDocumentId === document.id}
                          />
                        ) : null}
                        <Button
                          disabled={isDownloading}
                          onClick={() => onDownloadOne(document.id)}
                          variant="ghost"
                        >
                          <Download size={14} />
                          Скачать
                        </Button>
                        <Button
                          disabled={!canMutateDocuments}
                          onClick={() => onRemove(document.id)}
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
                          onClick={() => onCancelDraftExisting(document.id)}
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
                      <Button onClick={() => onCancelStaged(upload.id)} variant="ghost">
                        Убрать
                      </Button>
                    }
                    document={upload}
                    key={upload.id}
                  />
                ))}
              </>
            )}
          </DocumentListSection>

          <DocumentListSection
            className="bg-white"
            count={availableDocumentCount}
            title="Доступные документы"
          >
            {addableDocuments.length === 0 ? (
              <EmptyState>
                Нет дополнительных документов, доступных для добавления.
              </EmptyState>
            ) : (
              addableDocuments.map((document) => (
                <DocumentRow
                  action={
                    <>
                      <Button
                        disabled={!canMutateDocuments}
                        onClick={() => onAddExisting(document.id)}
                        variant="ghost"
                      >
                        Добавить
                      </Button>
                      {document.status === 'index_failed' ? (
                        <RetryIndexingButton
                          disabled={!canMutateDocuments || retryingDocumentId === document.id}
                          onClick={() => onRetry(document.id)}
                          pending={retryingDocumentId === document.id}
                        />
                      ) : null}
                      {canDeleteAvailableDocument(document, currentUserId) ? (
                        <Button
                          className="text-red-600 hover:bg-red-50 hover:text-red-700"
                          disabled={!canMutateDocuments}
                          onClick={() => onAskDelete(document)}
                          variant="ghost"
                        >
                          Удалить
                        </Button>
                      ) : null}
                    </>
                  }
                  document={document}
                  key={document.id}
                />
              ))
            )}
          </DocumentListSection>
        </div>
      </div>

      <div className="flex shrink-0 items-center justify-between border-t border-slate-100 px-6 py-4">
        <p className="text-sm text-slate-500">
          {hasDraftChanges
            ? 'Есть несохранённые изменения. Индексация начнётся после сохранения.'
            : 'Изменений пока нет.'}
        </p>
        <Button disabled={!hasDraftChanges || isSaving} onClick={onSave} variant="primary">
          {isSaving ? 'Сохраняем...' : 'Сохранить'}
        </Button>
      </div>
    </>
  )
}
