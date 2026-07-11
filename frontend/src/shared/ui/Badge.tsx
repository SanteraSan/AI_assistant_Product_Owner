import type { ReactNode } from 'react'
import { clsx } from 'clsx'

type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger'

type BadgeProps = {
  children: ReactNode
  tone?: BadgeTone
  className?: string
}

const tones: Record<BadgeTone, string> = {
  neutral: 'bg-slate-100 text-slate-700',
  success: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-700',
  danger: 'bg-rose-50 text-rose-700',
}

export function Badge({ children, className, tone = 'neutral' }: BadgeProps) {
  return (
    <span className={clsx('rounded-full px-2.5 py-1 text-xs font-medium', tones[tone], className)}>
      {children}
    </span>
  )
}
