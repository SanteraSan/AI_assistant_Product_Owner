import { FileText, Folder, Pencil, Plus, Upload } from 'lucide-react'
import { useState } from 'react'
import type { Bucket } from '../../entities/bucket/model'
import type { DocumentItem } from '../../entities/document/model'
import { Badge, Button, Card, Modal } from '../../shared/ui'

type BucketWorkspaceProps = {
  buckets: Bucket[]
  documents: DocumentItem[]
  onCreateBucket: () => void
  onSelectBucket: (bucketId: string) => void
}

const statusTone = {
  ready: 'success',
  indexing: 'warning',
  error: 'danger',
} as const

export function BucketWorkspace({
  buckets,
  documents,
  onCreateBucket,
  onSelectBucket,
}: BucketWorkspaceProps) {
  const [openedBucket, setOpenedBucket] = useState<Bucket | null>(null)

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
                <Button onClick={() => setOpenedBucket(bucket)} variant="secondary">
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
        isOpen={openedBucket !== null}
        onClose={() => setOpenedBucket(null)}
        title={openedBucket ? `Документы: ${openedBucket.name}` : 'Документы'}
      >
        <div className="mb-4 flex justify-end">
          <Button variant="primary">
            <Upload size={18} />
            Загрузить документ
          </Button>
        </div>
        <div className="space-y-3">
          {documents.map((document) => (
            <div
              className="flex items-center justify-between rounded-2xl border border-slate-200 p-4"
              key={document.id}
            >
              <div>
                <p className="font-medium text-slate-950">{document.fileName}</p>
                <p className="mt-1 text-sm text-slate-500">
                  {document.sourceType} · {document.uploadedAt}
                </p>
              </div>
              <Badge tone={document.status === 'indexed' ? 'success' : 'warning'}>
                {document.status}
              </Badge>
            </div>
          ))}
        </div>
      </Modal>
    </main>
  )
}
