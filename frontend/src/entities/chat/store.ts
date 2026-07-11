import { create } from 'zustand'
import { mockBuckets } from '../bucket/model'
import type { ChatMessage, ChatThread } from './model'
import { mockMessagesByThreadId, mockThreads } from './model'

type SendMessageContext = {
  bucketId: string
  bucketName: string
}

type ChatStore = {
  activeThreadId: string
  composerValue: string
  messagesByThreadId: Record<string, ChatMessage[]>
  threads: ChatThread[]
  createThread: () => void
  selectThread: (threadId: string) => void
  sendMessage: (text: string, context: SendMessageContext) => void
  setComposerValue: (value: string) => void
}

const initialThreadId = mockThreads[0]?.id ?? 'thread-1'

export const useChatStore = create<ChatStore>((set, get) => ({
  activeThreadId: initialThreadId,
  composerValue: '',
  messagesByThreadId: mockMessagesByThreadId,
  threads: mockThreads,

  createThread: () => {
    const threadId = `thread-${Date.now()}`
    const fallbackBucketId = mockBuckets[0]?.id ?? 'taskflow_seed'
    const newThread: ChatThread = {
      id: threadId,
      title: 'Новый чат',
      updatedAt: 'Только что',
      bucketId: fallbackBucketId,
    }

    set((state) => ({
      activeThreadId: threadId,
      composerValue: '',
      messagesByThreadId: {
        ...state.messagesByThreadId,
        [threadId]: [],
      },
      threads: [newThread, ...state.threads],
    }))
  },

  selectThread: (threadId: string) => {
    set({
      activeThreadId: threadId,
      composerValue: '',
    })
  },

  sendMessage: (text: string, context: SendMessageContext) => {
    const trimmedText = text.trim()
    if (!trimmedText) {
      return
    }

    const { activeThreadId } = get()
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: trimmedText,
    }
    const assistantMessage: ChatMessage = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content:
        'Пока это mock response. Следующий шаг — подключить `/rag/chat` и передавать туда model, tenant_id и выбранный bucket_ids.',
      sources: [
        {
          id: `source-${Date.now()}`,
          title: context.bucketName,
          sourceType: 'bucket',
        },
      ],
    }

    set((state) => ({
      composerValue: '',
      messagesByThreadId: {
        ...state.messagesByThreadId,
        [activeThreadId]: [
          ...(state.messagesByThreadId[activeThreadId] ?? []),
          userMessage,
          assistantMessage,
        ],
      },
      threads: state.threads.map((thread) =>
        thread.id === activeThreadId
          ? {
              ...thread,
              title: thread.title === 'Новый чат' ? trimmedText.slice(0, 48) : thread.title,
              updatedAt: 'Только что',
              bucketId: context.bucketId,
            }
          : thread,
      ),
    }))
  },

  setComposerValue: (value: string) => {
    set({ composerValue: value })
  },
}))
