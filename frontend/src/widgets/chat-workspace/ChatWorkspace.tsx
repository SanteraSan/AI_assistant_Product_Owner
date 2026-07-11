import { Bot, FileText, UserRound } from 'lucide-react'
import type { ChatMessage } from '../../entities/chat/model'
import type { Bucket } from '../../entities/bucket/model'
import type { LocalModel, ModelApproach } from '../../entities/model/model'
import { MessageComposer } from '../../features/send-message/MessageComposer'
import { Badge, Card } from '../../shared/ui'

type ChatWorkspaceProps = {
  activeBucket?: Bucket
  approach: ModelApproach
  attachDisabled?: boolean
  composerValue: string
  messages: ChatMessage[]
  selectedModel?: LocalModel
  onChangeComposerValue: (value: string) => void
  onAttachFile?: (file: File) => void
  onSendMessage: () => void
}

export function ChatWorkspace({
  activeBucket,
  approach,
  attachDisabled,
  composerValue,
  messages,
  onAttachFile,
  onChangeComposerValue,
  onSendMessage,
  selectedModel,
}: ChatWorkspaceProps) {
  const latestAssistantMessage = [...messages].reverse().find((message) => message.role === 'assistant')
  const latestSources = latestAssistantMessage?.sources ?? []

  return (
    <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_320px] bg-slate-50">
      <section className="flex min-h-0 flex-col">
        <div className="flex-1 space-y-4 overflow-y-auto px-8 py-6">
          <Card className="p-5">
            <p className="text-sm font-medium text-slate-500">Активный контекст</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge>{activeBucket?.name ?? 'Bucket не выбран'}</Badge>
              <Badge>{selectedModel?.label ?? 'Модель не выбрана'}</Badge>
              <Badge>{approach}</Badge>
            </div>
          </Card>

          {messages.map((message) => (
            <div
              className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              key={message.id}
            >
              {message.role === 'assistant' && (
                <div className="mt-1 flex h-9 w-9 items-center justify-center rounded-full bg-slate-950 text-white">
                  <Bot size={18} />
                </div>
              )}
              <div
                className={`max-w-3xl rounded-3xl px-5 py-4 text-sm leading-6 ${
                  message.role === 'user'
                    ? 'bg-slate-950 text-white'
                    : 'border border-slate-200 bg-white text-slate-800'
                }`}
              >
                {message.content}
                {message.attachments?.length ? (
                  <div className="mt-3 space-y-2">
                    {message.attachments.map((attachment) => (
                      <div
                        className="flex items-center justify-between gap-3 rounded-2xl bg-white/10 px-3 py-2 text-xs"
                        key={attachment.id}
                      >
                        <span className="inline-flex items-center gap-2">
                          <FileText size={16} />
                          {attachment.fileName}
                        </span>
                        <Badge tone={attachment.status === 'indexed' ? 'success' : 'warning'}>
                          {attachment.status}
                        </Badge>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
              {message.role === 'user' && (
                <div className="mt-1 flex h-9 w-9 items-center justify-center rounded-full bg-white text-slate-700">
                  <UserRound size={18} />
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="border-t border-slate-200 bg-slate-50 px-8 py-5">
          <MessageComposer
            attachDisabled={attachDisabled}
            onAttachFile={onAttachFile}
            onChange={onChangeComposerValue}
            onSubmit={onSendMessage}
            value={composerValue}
          />
        </div>
      </section>

      <aside className="border-l border-slate-200 bg-white p-5">
        <h2 className="text-base font-semibold text-slate-950">Источники ответа</h2>
        <p className="mt-1 text-sm text-slate-500">
          Здесь будут документы и фрагменты, на которые опирался последний RAG ответ.
        </p>
        <div className="mt-4 space-y-3">
          {latestSources.length ? (
            latestSources.map((source) => (
              <Card className="p-4" key={source.id}>
                <p className="text-sm font-medium text-slate-900">{source.title}</p>
                <p className="mt-2 text-xs text-slate-500">{source.sourceType}</p>
              </Card>
            ))
          ) : (
            <Card className="p-4">
              <p className="text-sm text-slate-500">
                Источники появятся после ответа, который использует RAG context.
              </p>
            </Card>
          )}
        </div>
      </aside>
    </main>
  )
}
