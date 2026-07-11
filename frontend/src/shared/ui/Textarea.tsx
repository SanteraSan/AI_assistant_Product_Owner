import type { TextareaHTMLAttributes } from 'react'
import { clsx } from 'clsx'

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>

export function Textarea({ className, ...props }: TextareaProps) {
  return (
    <textarea
      className={clsx(
        'min-h-24 w-full resize-none rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-400',
        className,
      )}
      {...props}
    />
  )
}
