import { Paperclip, Send, SlidersHorizontal } from 'lucide-react'
import { useRef } from 'react'
import { Button, Textarea } from '../../shared/ui'

type MessageComposerProps = {
  value: string
  attachDisabled?: boolean
  disabled?: boolean
  onChange: (value: string) => void
  onAttachFile?: (file: File) => void
  onSubmit: () => void
}

export function MessageComposer({
  attachDisabled,
  disabled,
  onAttachFile,
  onChange,
  onSubmit,
  value,
}: MessageComposerProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-3 shadow-lg shadow-slate-200/70">
      <Textarea
        className="border-0 px-2 py-2 shadow-none focus:border-0"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            onSubmit()
          }
        }}
        placeholder="Введите сообщение..."
        value={value}
      />
      <div className="flex items-center justify-between px-1 pt-2">
        <div className="flex items-center gap-2">
          <input
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) {
                onAttachFile?.(file)
              }
              event.target.value = ''
            }}
            ref={fileInputRef}
            type="file"
          />
          <Button
            aria-label="Прикрепить файл"
            className="h-11 w-11 p-0"
            disabled={attachDisabled}
            onClick={() => fileInputRef.current?.click()}
            variant="ghost"
          >
            <Paperclip size={20} />
          </Button>
          <Button aria-label="Настройки запроса" className="h-11 w-11 p-0" variant="ghost">
            <SlidersHorizontal size={20} />
          </Button>
        </div>
        <Button disabled={disabled || !value.trim()} onClick={onSubmit} variant="primary">
          <Send size={20} />
          Отправить
        </Button>
      </div>
    </div>
  )
}
