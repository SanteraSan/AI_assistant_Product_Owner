import { ConfirmDialog } from '../../shared/ui'

type DeleteDocumentDialogProps = {
  error: string | null
  fileName: string
  isDeleting: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function DeleteDocumentDialog({
  error,
  fileName,
  isDeleting,
  onCancel,
  onConfirm,
}: DeleteDocumentDialogProps) {
  return (
    <ConfirmDialog
      confirmLabel="Удалить"
      danger
      error={error}
      errorTone="warning"
      onCancel={onCancel}
      onConfirm={onConfirm}
      pending={isDeleting}
      pendingLabel="Удаляем..."
    >
      <p className="text-sm leading-6 text-slate-600">
        Вы точно хотите удалить файл{' '}
        <span className="font-semibold text-slate-950">
          {fileName}
        </span>
        ? Это удалит его из личной библиотеки документов.
      </p>
    </ConfirmDialog>
  )
}
