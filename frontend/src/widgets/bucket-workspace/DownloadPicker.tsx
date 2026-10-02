import { useEffect, useRef } from 'react'
import type { DocumentItem } from '../../entities/document/model'
import { DialogActions, Notice } from '../../shared/ui'

type DownloadPickerProps = {
  documents: DocumentItem[]
  error: string | null
  isDownloading: boolean
  onCancel: () => void
  onDownload: () => void
  onToggle: (documentId: string) => void
  onToggleAll: () => void
  selectedIds: string[]
}

export function DownloadPicker({
  documents,
  error,
  isDownloading,
  onCancel,
  onDownload,
  onToggle,
  onToggleAll,
  selectedIds,
}: DownloadPickerProps) {
  const selectAllRef = useRef<HTMLInputElement>(null)
  const selectedIdSet = new Set(selectedIds)
  const allSelected = documents.length > 0 && selectedIds.length === documents.length
  const noneSelected = selectedIds.length === 0

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = !allSelected && !noneSelected
    }
  }, [allSelected, noneSelected])

  return (
    <>
      <div className="shrink-0 border-b border-slate-100 px-6 py-4">
        <label className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-medium text-slate-900">
          <input
            checked={allSelected}
            className="h-4 w-4 shrink-0 rounded border-slate-300"
            onChange={onToggleAll}
            ref={selectAllRef}
            type="checkbox"
          />
          Выбрать все
        </label>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-6 py-4">
        {documents.map((document) => (
          <label
            className="flex items-center gap-3 rounded-2xl border border-slate-200 px-4 py-3 text-sm text-slate-800"
            key={document.id}
          >
            <input
              checked={selectedIdSet.has(document.id)}
              className="h-4 w-4 shrink-0 rounded border-slate-300"
              onChange={() => onToggle(document.id)}
              type="checkbox"
            />
            <span className="flex min-w-0 flex-1 items-center justify-between gap-3">
              <span className="truncate font-medium text-slate-950" title={document.fileName}>
                {document.fileName}
              </span>
              <span className="shrink-0 text-xs text-slate-500">{document.sourceType}</span>
            </span>
          </label>
        ))}
        {error ? <Notice compact>{error}</Notice> : null}
      </div>
      <DialogActions
        cancelLabel="Отменить"
        className="shrink-0 border-t border-slate-100 px-6 py-4"
        confirmDisabled={noneSelected}
        confirmLabel="Скачать"
        onCancel={onCancel}
        onConfirm={onDownload}
        pending={isDownloading}
        pendingLabel="Скачиваем..."
      />
    </>
  )
}
