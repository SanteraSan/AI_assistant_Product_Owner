import { clsx } from 'clsx'
import { Button } from './Button'

type DialogActionsProps = {
  cancelLabel?: string
  className?: string
  confirmDisabled?: boolean
  confirmLabel: string
  danger?: boolean
  onCancel: () => void
  onConfirm: () => void
  pending?: boolean
  pendingLabel: string
}

export function DialogActions({
  cancelLabel = 'Отмена',
  className,
  confirmDisabled = false,
  confirmLabel,
  danger = false,
  onCancel,
  onConfirm,
  pending = false,
  pendingLabel,
}: DialogActionsProps) {
  return (
    <div className={clsx('flex justify-end gap-2', className)}>
      <Button disabled={pending} onClick={onCancel} variant="secondary">
        {cancelLabel}
      </Button>
      <Button
        disabled={pending || confirmDisabled}
        onClick={onConfirm}
        variant={danger ? 'danger' : 'primary'}
      >
        {pending ? pendingLabel : confirmLabel}
      </Button>
    </div>
  )
}
