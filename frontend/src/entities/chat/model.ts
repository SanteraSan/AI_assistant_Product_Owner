export type ChatMode = 'rag' | 'agent'

export type ToolTraceItem = {
  id: string
  name: string
  status: string
  latencyMs?: number
  errorCode?: string | null
  errorMessage?: string | null
}

export type ChatThread = {
  id: string
  title: string
  updatedAt: string
  bucketId: string
  sessionId?: string
  bucketIds?: string[]
  documentIds?: string[]
  modelId?: string
  approach?: string
}

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  attachments?: ChatAttachment[]
  sources?: Array<{
    id: string
    title: string
    sourceType: string
  }>
  toolCalls?: ToolTraceItem[]
}

export type ChatAttachment = {
  id: string
  fileName: string
  sourceType: string
  status: 'uploaded' | 'indexing' | 'indexed' | 'index_failed' | 'error'
}

export const mockThreads: ChatThread[] = [
  {
    id: 'thread-1',
    title: 'M5 regression summary',
    updatedAt: 'Сегодня',
    bucketId: 'taskflow_seed',
  },
  {
    id: 'thread-2',
    title: 'Text-to-SQL LoRA V5',
    updatedAt: 'Вчера',
    bucketId: 'm5_documents',
  },
]

export const mockMessagesByThreadId: Record<string, ChatMessage[]> = {
  'thread-1': [
    {
      id: 'msg-1',
      role: 'assistant',
      content:
        'Привет! Это отдельный чат по M5 regression. Выбери bucket, модель и подход, затем задай вопрос.',
      sources: [
        {
          id: 'source-1',
          title: 'M5_FULL_REGRESSION_2026_07_09.md',
          sourceType: 'research',
        },
      ],
    },
  ],
  'thread-2': [
    {
      id: 'msg-2',
      role: 'assistant',
      content:
        'Это отдельный чат по Text-to-SQL LoRA V5. Его сообщения сохраняются отдельно от других чатов.',
      sources: [
        {
          id: 'source-2',
          title: 'TEXT_TO_SQL_LORA_V5_PROJECTION_2026_07_10.md',
          sourceType: 'research',
        },
      ],
    },
  ],
}
