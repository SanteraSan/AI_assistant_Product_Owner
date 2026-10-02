import { MessageSquarePlus, Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import type { ChatThread } from '../../entities/chat/model'
import { Button, ConfirmDialog, DialogActions, Input, Modal, Notice } from '../../shared/ui'

type ChatSidebarProps = {
  threads: ChatThread[]
  activeThreadId: string | null
  onSelectThread: (threadId: string) => void
  onCreateThread: () => void
  onRenameThread: (threadId: string, title: string) => Promise<void>
  onDeleteThread: (threadId: string) => Promise<void>
}

export function ChatSidebar({
  activeThreadId,
  onCreateThread,
  onDeleteThread,
  onRenameThread,
  onSelectThread,
  threads,
}: ChatSidebarProps) {
  const [threadToRename, setThreadToRename] = useState<ChatThread | null>(null)
  const [threadToDelete, setThreadToDelete] = useState<ChatThread | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  async function handleRename() {
    if (threadToRename === null) {
      return
    }
    const nextTitle = renameValue.trim()
    if (!nextTitle) {
      setActionError('Название чата не может быть пустым.')
      return
    }
    setIsSaving(true)
    setActionError(null)
    try {
      await onRenameThread(threadToRename.id, nextTitle)
      setThreadToRename(null)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Не удалось переименовать чат.')
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDelete() {
    if (threadToDelete === null) {
      return
    }
    setIsSaving(true)
    setActionError(null)
    try {
      await onDeleteThread(threadToDelete.id)
      setThreadToDelete(null)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Не удалось удалить чат.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <aside className="flex h-full w-72 flex-col border-r border-slate-200 bg-slate-950 p-4 text-white">
      <div className="mb-6">
        <p className="text-sm text-slate-400">Product Owner Assistant</p>
        <h1 className="mt-1 text-xl font-semibold">AI Workspace</h1>
      </div>

      <Button
        className="mb-4 border-slate-700 bg-white text-slate-950 hover:bg-slate-100"
        onClick={onCreateThread}
      >
        <MessageSquarePlus size={20} />
        Новый чат
      </Button>

      <div className="flex flex-1 flex-col gap-2 overflow-y-auto">
        <p className="px-3 text-xs font-medium uppercase tracking-wide text-slate-500">
          История чатов
        </p>
        {threads.map((thread) => (
          <div
            className={`group flex items-start gap-1 rounded-xl px-2 py-2 transition ${
              thread.id === activeThreadId
                ? 'bg-white text-slate-950'
                : 'text-slate-300 hover:bg-slate-900 hover:text-white'
            }`}
            key={thread.id}
          >
            <button
              className="min-w-0 flex-1 rounded-lg px-1 py-1 text-left text-sm"
              onClick={() => onSelectThread(thread.id)}
              type="button"
            >
              <span className="block truncate font-medium">{thread.title}</span>
              <span className="mt-1 block text-xs opacity-70">{thread.updatedAt}</span>
            </button>
            <button
              aria-label="Переименовать чат"
              className={`mt-1 rounded-lg p-1.5 opacity-0 transition group-hover:opacity-100 ${
                thread.id === activeThreadId
                  ? 'hover:bg-slate-100'
                  : 'hover:bg-slate-800'
              }`}
              onClick={(event) => {
                event.stopPropagation()
                setActionError(null)
                setRenameValue(thread.title)
                setThreadToRename(thread)
              }}
              type="button"
            >
              <Pencil size={14} />
            </button>
            <button
              aria-label="Удалить чат"
              className={`mt-1 rounded-lg p-1.5 opacity-0 transition group-hover:opacity-100 ${
                thread.id === activeThreadId
                  ? 'text-red-600 hover:bg-red-50'
                  : 'text-red-300 hover:bg-slate-800'
              }`}
              onClick={(event) => {
                event.stopPropagation()
                setActionError(null)
                setThreadToDelete(thread)
              }}
              type="button"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      <Modal
        isOpen={threadToRename !== null}
        onClose={() => {
          if (!isSaving) {
            setThreadToRename(null)
            setActionError(null)
          }
        }}
        title="Переименовать чат"
      >
        <div className="space-y-4">
          <Input onChange={(event) => setRenameValue(event.target.value)} value={renameValue} />
          {actionError && threadToRename ? <Notice compact>{actionError}</Notice> : null}
          <DialogActions
            confirmLabel="Сохранить"
            onCancel={() => setThreadToRename(null)}
            onConfirm={() => {
              void handleRename()
            }}
            pending={isSaving}
            pendingLabel="Сохраняем..."
          />
        </div>
      </Modal>

      <Modal
        isOpen={threadToDelete !== null}
        onClose={() => {
          if (!isSaving) {
            setThreadToDelete(null)
            setActionError(null)
          }
        }}
        title="Удалить чат?"
      >
        <ConfirmDialog
          confirmLabel="Удалить"
          danger
          error={actionError && threadToDelete ? actionError : null}
          errorCompact
          onCancel={() => setThreadToDelete(null)}
          onConfirm={() => {
            void handleDelete()
          }}
          pending={isSaving}
          pendingLabel="Удаляем..."
        >
          <p className="text-sm leading-6 text-slate-600">
            Чат{' '}
            <span className="font-semibold text-slate-950">{threadToDelete?.title}</span> будет
            удалён вместе с историей сообщений.
          </p>
        </ConfirmDialog>
      </Modal>
    </aside>
  )
}
