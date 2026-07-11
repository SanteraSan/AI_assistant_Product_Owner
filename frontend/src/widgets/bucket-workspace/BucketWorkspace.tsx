import { FileText, Folder, Pencil, Plus, Upload } from 'lucide-react'
import type { ReactNode } from 'react'
import { useRef, useState } from 'react'
import type { Bucket } from '../../entities/bucket/model'
import type { DocumentItem } from '../../entities/document/model'
import { Badge, Button, Card, Modal } from '../../shared/ui'

type BucketWorkspaceProps = {
  buckets: Bucket[]
  availableDocuments: DocumentItem[]
  documents: DocumentItem[]
  onAddDocumentToBucket: (bucketId: string, documentId: string) => void
  onCreateBucket: () => void
  onInspectBucket: (bucketId: string) => void
  onSelectBucket: (bucketId: string) => void
  onUploadDocument: (bucketId: string, file: File) => void
}

const statusTone = {
  ready: 'success',
  indexing: 'warning',
  error: 'danger',
} as const

export function BucketWorkspace({
  availableDocuments,
  buckets,
  documents,
  onAddDocumentToBucket,
  onCreateBucket,
  onInspectBucket,
  onSelectBucket,
  onUploadDocument,
}: BucketWorkspaceProps) {
  const [openedBucket, setOpenedBucket] = useState<Bucket | null>(null)
  const uploadInputRef = useRef<HTMLInputElement | null>(null)
  const documentsInBucket = new Set(documents.map((document) => document.id))
  const addableDocuments = availableDocuments.filter((document) => !documentsInBucket.has(document.id))

  function openDocuments(bucket: Bucket) {
    onInspectBucket(bucket.id)
    setOpenedBucket(bucket)
  }

  function handleUpload(file: File | undefined) {
    if (!file || openedBucket === null) {
      return
    }
    onUploadDocument(openedBucket.id, file)
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
        isOpen={openedBucket !== null}
        onClose={() => setOpenedBucket(null)}
        title={openedBucket ? `Документы: ${openedBucket.name}` : 'Документы'}
      >
        <div className="mb-4 flex items-center justify-between gap-3">
          <p className="text-sm text-slate-500">
            Bucket хранит ссылки на документы. Доступ всё равно проверяется по owner/role/tenant.
          </p>
          <input
            className="hidden"
            onChange={(event) => handleUpload(event.target.files?.[0])}
            ref={uploadInputRef}
            type="file"
          />
          <Button onClick={() => uploadInputRef.current?.click()} variant="primary">
            <Upload size={18} />
            Загрузить документ
          </Button>
        </div>

        <section>
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            В этом bucket
          </h3>
          <div className="space-y-3">
            {documents.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-slate-200 p-4 text-sm text-slate-500">
                Документов пока нет. Можно загрузить новый или добавить доступный из библиотеки.
              </p>
            ) : (
              documents.map((document) => (
                <DocumentRow document={document} key={document.id} />
              ))
            )}
          </div>
        </section>

        <section className="mt-6">
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Доступные документы
          </h3>
          <div className="space-y-3">
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
                        onClick={() => onAddDocumentToBucket(openedBucket.id, document.id)}
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
      </Modal>
    </main>
  )
}

function DocumentRow({
  action,
  document,
}: {
  action?: ReactNode
  document: DocumentItem
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-2xl border border-slate-200 p-4">
      <div>
        <p className="font-medium text-slate-950">{document.fileName}</p>
        <p className="mt-1 text-sm text-slate-500">
          {document.sourceType} · {document.visibility} · {document.uploadedAt}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Badge tone={document.status === 'indexed' ? 'success' : 'warning'}>
          {document.status}
        </Badge>
        {action}
      </div>
    </div>
  )
}
