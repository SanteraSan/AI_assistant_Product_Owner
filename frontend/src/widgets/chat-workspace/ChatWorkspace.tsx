import { Bot, FileText, UserRound } from 'lucide-react'
import type { ChatMessage, ChatMode } from '../../entities/chat/model'
import type { Bucket } from '../../entities/bucket/model'
import type { LocalModel, ModelApproach } from '../../entities/model/model'
import { MessageComposer } from '../../features/send-message/MessageComposer'
import { Badge, Card } from '../../shared/ui'

type ChatWorkspaceProps = {
  activeBucket?: Bucket
  approach: ModelApproach
  chatMode: ChatMode
  attachDisabled?: boolean
  composerValue: string
  isSending?: boolean
  messages: ChatMessage[]
  selectedModel?: LocalModel
  onChangeComposerValue: (value: string) => void
  onAttachFile?: (file: File) => void
  onSendMessage: () => void
}

export function ChatWorkspace({
  activeBucket,
  approach,
  chatMode,
  attachDisabled,
  composerValue,
  isSending,
  messages,
  onAttachFile,
  onChangeComposerValue,
  onSendMessage,
  selectedModel,
}: ChatWorkspaceProps) {
  const latestAssistantMessage = [...messages].reverse().find((message) => message.role === 'assistant')
  const latestSources = latestAssistantMessage?.sources ?? []
  const latestToolCalls = latestAssistantMessage?.toolCalls ?? []

  return (
    <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_320px] bg-slate-50">
      <section className="flex min-h-0 flex-col">
        <div className="flex-1 space-y-4 overflow-y-auto px-8 py-6">
          <Card className="p-5">
            <p className="text-sm font-medium text-slate-500">Активный контекст</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge>{chatMode === 'agent' ? 'Agent' : 'RAG'}</Badge>
              <Badge>{activeBucket?.name ?? 'Без bucket'}</Badge>
              <Badge>{selectedModel?.label ?? 'Модель не выбрана'}</Badge>
              <Badge>{approach}</Badge>
            </div>
            {approach === 'external' ? (
              <p className="mt-3 text-sm text-amber-800">
                Запрос уйдёт во внешнюю модель (Gemini/OpenRouter). Текст сообщения отправится
                провайдеру.
              </p>
            ) : null}
            {chatMode === 'agent' && approach === 'external' ? (
              <p className="mt-2 text-sm text-amber-800">
                Agent в этом срезе работает только на Ollama. Выберите Гибрид или Только локальные.
              </p>
            ) : null}
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
          {isSending ? (
            <div className="flex justify-start gap-3">
              <div className="mt-1 flex h-9 w-9 items-center justify-center rounded-full bg-slate-950 text-white">
                <Bot size={18} />
              </div>
              <div className="rounded-3xl border border-slate-200 bg-white px-5 py-4 text-sm leading-6 text-slate-500">
                {chatMode === 'agent' ? 'Агент вызывает tools...' : 'Думаю над ответом...'}
              </div>
            </div>
          ) : null}
        </div>

        <div className="border-t border-slate-200 bg-slate-50 px-8 py-5">
          <MessageComposer
            attachDisabled={attachDisabled}
            disabled={isSending}
            onAttachFile={onAttachFile}
            onChange={onChangeComposerValue}
            onSubmit={onSendMessage}
            value={composerValue}
          />
        </div>
      </section>

      <aside className="space-y-8 overflow-y-auto border-l border-slate-200 bg-white p-5">
        <section>
          <h2 className="text-base font-semibold text-slate-950">Источники ответа</h2>
          <p className="mt-1 text-sm text-slate-500">
            Документы и фрагменты, на которые опирался последний ответ.
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
                  Источники появятся после ответа с evidence.
                </p>
              </Card>
            )}
          </div>
        </section>

        <section>
          <h2 className="text-base font-semibold text-slate-950">Tool trace</h2>
          <p className="mt-1 text-sm text-slate-500">
            Вызовы инструментов последнего agent-ответа.
          </p>
          <div className="mt-4 space-y-3">
            {latestToolCalls.length ? (
              latestToolCalls.map((call) => (
                <Card className="p-4" key={call.id}>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-900">{call.name}</p>
                    <Badge tone={call.status === 'ok' ? 'success' : 'warning'}>{call.status}</Badge>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    {call.latencyMs != null ? `${call.latencyMs} ms` : '—'}
                    {call.errorCode ? ` · ${call.errorCode}` : ''}
                  </p>
                  {call.errorMessage ? (
                    <p className="mt-2 text-xs text-slate-600">{call.errorMessage}</p>
                  ) : null}
                </Card>
              ))
            ) : (
              <Card className="p-4">
                <p className="text-sm text-slate-500">
                  Trace появится в режиме Agent после tool calls.
                </p>
              </Card>
            )}
          </div>
        </section>
      </aside>
    </main>
  )
}
