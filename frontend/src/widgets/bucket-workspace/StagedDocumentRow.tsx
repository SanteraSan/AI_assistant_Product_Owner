import type { ReactNode } from 'react'
import type { StagedDocumentItem } from '../../entities/document/model'
import { Badge } from '../../shared/ui'

type StagedDocumentRowProps = {
  action?: ReactNode
  document: StagedDocumentItem
}

export function StagedDocumentRow({ action, document }: StagedDocumentRowProps) {
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
