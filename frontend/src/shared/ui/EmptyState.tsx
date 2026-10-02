import type { ReactNode } from 'react'
import { clsx } from 'clsx'

type EmptyStateProps = {
  children: ReactNode
  className?: string
  filled?: boolean
}

export function EmptyState({ children, className, filled = false }: EmptyStateProps) {
  return (
    <p
      className={clsx(
        'rounded-2xl border border-dashed border-slate-200 p-4 text-sm text-slate-500',
        filled && 'bg-white',
        className,
      )}
    >
      {children}
    </p>
  )
}
