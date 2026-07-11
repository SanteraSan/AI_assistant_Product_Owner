import type { SelectHTMLAttributes } from 'react'
import { clsx } from 'clsx'

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  label: string
  options: Array<{
    value: string
    label: string
  }>
}

export function Select({ className, label, options, ...props }: SelectProps) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-slate-500">
      {label}
      <select
        className={clsx(
          'h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-slate-400',
          className,
        )}
        {...props}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}
