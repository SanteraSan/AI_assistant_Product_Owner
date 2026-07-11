import { create } from 'zustand'
import { mockBuckets } from '../bucket/model'
import type { ChatAttachment, ChatMessage, ChatThread } from './model'
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
  addAttachmentMessage: (attachment: ChatAttachment) => void
  selectThread: (threadId: string) => void
  sendMessage: (text: string, context: SendMessageContext) => void
  setComposerValue: (value: string) => void
  updateAttachmentStatuses: (attachments: ChatAttachment[]) => void
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

  addAttachmentMessage: (attachment: ChatAttachment) => {
    const { activeThreadId } = get()
    const message: ChatMessage = {
      id: `attachment-${Date.now()}`,
      role: 'user',
      content: `Прикреплён файл: ${attachment.fileName}`,
      attachments: [attachment],
    }

    set((state) => ({
      messagesByThreadId: {
        ...state.messagesByThreadId,
        [activeThreadId]: [
          ...(state.messagesByThreadId[activeThreadId] ?? []),
          message,
        ],
      },
      threads: state.threads.map((thread) =>
        thread.id === activeThreadId
          ? {
              ...thread,
              title: thread.title === 'Новый чат' ? attachment.fileName.slice(0, 48) : thread.title,
              updatedAt: 'Только что',
            }
          : thread,
      ),
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

  updateAttachmentStatuses: (attachments: ChatAttachment[]) => {
    if (!attachments.length) {
      return
    }
    const statusById = new Map(attachments.map((attachment) => [attachment.id, attachment.status]))
    set((state) => ({
      messagesByThreadId: Object.fromEntries(
        Object.entries(state.messagesByThreadId).map(([threadId, messages]) => [
          threadId,
          messages.map((message) => ({
            ...message,
            attachments: message.attachments?.map((attachment) => ({
              ...attachment,
              status: statusById.get(attachment.id) ?? attachment.status,
            })),
          })),
        ]),
      ),
    }))
  },
}))
