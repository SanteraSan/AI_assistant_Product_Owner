import type { ReactNode } from 'react'
import { clsx } from 'clsx'

type DocumentListSectionProps = {
  children: ReactNode
  className?: string
  count: number
  title: string
}

export function DocumentListSection({ children, className, count, title }: DocumentListSectionProps) {
  return (
    <section className={clsx('flex min-h-0 flex-col overflow-hidden rounded-3xl border border-slate-100 p-4', className)}>
      <h3 className="mb-3 shrink-0 text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
        {count > 0 ? <span className="ml-2 text-slate-400">{count}</span> : null}
      </h3>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {children}
      </div>
    </section>
  )
}
