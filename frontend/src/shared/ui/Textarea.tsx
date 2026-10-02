import type { TextareaHTMLAttributes } from 'react'
import { clsx } from 'clsx'

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  variant?: 'default' | 'field'
}

const variants = {
  default:
    'min-h-24 w-full resize-none rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-400',
  field:
    'min-h-24 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-950 outline-none focus:border-slate-400',
}

export function Textarea({ className, variant = 'default', ...props }: TextareaProps) {
  return (
    <textarea
      className={clsx(variants[variant], className)}
      {...props}
    />
  )
}
