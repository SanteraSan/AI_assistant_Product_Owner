import type { HTMLAttributes, ReactNode } from 'react'
import { clsx } from 'clsx'

type CardProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode
}

export function Card({ children, className, ...props }: CardProps) {
  return (
    <div
      className={clsx('rounded-2xl border border-slate-200 bg-white shadow-sm', className)}
      {...props}
    >
      {children}
    </div>
  )
}
