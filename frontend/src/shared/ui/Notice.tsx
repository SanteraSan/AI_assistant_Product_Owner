import type { ReactNode } from 'react'
import { clsx } from 'clsx'

type NoticeTone = 'error' | 'warning'

type NoticeProps = {
  children: ReactNode
  className?: string
  compact?: boolean
  tone?: NoticeTone
}

const tones: Record<NoticeTone, string> = {
  error: 'border-red-200 bg-red-50 text-red-700',
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
}

export function Notice({ children, className, compact = false, tone = 'error' }: NoticeProps) {
  return (
    <p
      className={clsx(
        'rounded-2xl border text-sm',
        compact ? 'p-3' : 'p-4',
        tones[tone],
        className,
      )}
    >
      {children}
    </p>
  )
}
