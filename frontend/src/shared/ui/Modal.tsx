import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { Button } from './Button'

type ModalProps = {
  title: string
  isOpen: boolean
  children: ReactNode
  onClose: () => void
}

export function Modal({ children, isOpen, onClose, title }: ModalProps) {
  if (!isOpen) {
    return null
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
      <div className="w-full max-w-2xl rounded-3xl bg-white p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
          <Button aria-label="Закрыть" className="h-9 w-9 p-0" onClick={onClose} variant="ghost">
            <X size={18} />
          </Button>
        </div>
        {children}
      </div>
    </div>
  )
}
