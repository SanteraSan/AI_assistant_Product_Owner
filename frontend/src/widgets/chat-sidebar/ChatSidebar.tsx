import { MessageSquarePlus } from 'lucide-react'
import type { ChatThread } from '../../entities/chat/model'
import { Button } from '../../shared/ui'

type ChatSidebarProps = {
  threads: ChatThread[]
  activeThreadId: string | null
  onSelectThread: (threadId: string) => void
  onCreateThread: () => void
}

export function ChatSidebar({
  activeThreadId,
  onCreateThread,
  onSelectThread,
  threads,
}: ChatSidebarProps) {
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
          <button
            className={`rounded-xl px-3 py-3 text-left text-sm transition ${
              thread.id === activeThreadId
                ? 'bg-white text-slate-950'
                : 'text-slate-300 hover:bg-slate-900 hover:text-white'
            }`}
            key={thread.id}
            onClick={() => onSelectThread(thread.id)}
            type="button"
          >
            <span className="block truncate font-medium">{thread.title}</span>
            <span className="mt-1 block text-xs opacity-70">{thread.updatedAt}</span>
          </button>
        ))}
      </div>
    </aside>
  )
}
