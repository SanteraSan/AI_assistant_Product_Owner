import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { clsx } from 'clsx'

type ModalProps = {
  title: string
  isOpen: boolean
  children: ReactNode
  bodyClassName?: string
  onClose: () => void
  size?: 'default' | 'lg'
}

export function Modal({
  bodyClassName,
  children,
  isOpen,
  onClose,
  size = 'default',
  title,
}: ModalProps) {
  if (!isOpen) {
    return null
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
      <div
        className={clsx(
          'flex w-full flex-col rounded-3xl bg-white shadow-2xl',
          size === 'lg' ? 'h-[80vh] max-w-4xl' : 'max-w-2xl',
        )}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-slate-100 px-6 py-4">
          <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
          <button
            aria-label="Закрыть"
            className="inline-flex h-9 w-9 items-center justify-center rounded-xl text-slate-600 transition hover:bg-slate-100 hover:text-slate-950"
            onClick={onClose}
            type="button"
          >
            <X aria-hidden="true" size={18} strokeWidth={2} />
          </button>
        </div>
        <div className={clsx('min-h-0 p-6', bodyClassName)}>{children}</div>
      </div>
    </div>
  )
}
