import type { ReactNode } from 'react'
import type { DocumentItem } from '../../entities/document/model'
import { Badge } from '../../shared/ui'
import { statusToneForDocument } from './documentRules'

type DocumentRowProps = {
  action?: ReactNode
  document: DocumentItem
}

export function DocumentRow({ action, document }: DocumentRowProps) {
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
