import type { ReactNode } from 'react'
import { DialogActions } from './DialogActions'
import { Notice } from './Notice'

type ConfirmDialogProps = {
  children: ReactNode
  confirmLabel: string
  danger?: boolean
  error: string | null
  errorCompact?: boolean
  errorTone?: 'error' | 'warning'
  onCancel: () => void
  onConfirm: () => void
  pending: boolean
  pendingLabel: string
}

export function ConfirmDialog({
  children,
  confirmLabel,
  danger = false,
  error,
  errorCompact = false,
  errorTone = 'error',
  onCancel,
  onConfirm,
  pending,
  pendingLabel,
}: ConfirmDialogProps) {
  return (
    <div className="space-y-4">
      {children}
      {error ? (
        <Notice compact={errorCompact} tone={errorTone}>
          {error}
        </Notice>
      ) : null}
      <DialogActions
        confirmLabel={confirmLabel}
        danger={danger}
        onCancel={onCancel}
        onConfirm={onConfirm}
        pending={pending}
        pendingLabel={pendingLabel}
      />
    </div>
  )
}
