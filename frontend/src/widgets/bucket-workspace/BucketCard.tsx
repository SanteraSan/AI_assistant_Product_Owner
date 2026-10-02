import { FileText, Folder, Pencil, Trash2 } from 'lucide-react'
import type { Bucket } from '../../entities/bucket/model'
import { Badge, Button, Card } from '../../shared/ui'

const statusTone = {
  ready: 'success',
  indexing: 'warning',
  error: 'danger',
} as const

type BucketCardProps = {
  bucket: Bucket
  canMutateDocuments: boolean
  onDelete: (bucket: Bucket) => void
  onEdit: (bucket: Bucket) => void
  onOpenDocuments: (bucket: Bucket) => void
  onSelect: (bucketId: string) => void
}

export function BucketCard({
  bucket,
  canMutateDocuments,
  onDelete,
  onEdit,
  onOpenDocuments,
  onSelect,
}: BucketCardProps) {
  return (
    <Card className="p-5">
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
          <Button onClick={() => onSelect(bucket.id)} variant="ghost">
            Выбрать
          </Button>
          <Button onClick={() => onOpenDocuments(bucket)} variant="secondary">
            <FileText size={16} />
            Документы
          </Button>
          <Button
            disabled={!canMutateDocuments}
            onClick={() => onEdit(bucket)}
            variant="ghost"
          >
            <Pencil size={16} />
          </Button>
          <Button
            className="text-red-600 hover:bg-red-50 hover:text-red-700"
            disabled={!canMutateDocuments}
            onClick={() => onDelete(bucket)}
            variant="ghost"
          >
            <Trash2 size={16} />
          </Button>
        </div>
      </div>
    </Card>
  )
}
