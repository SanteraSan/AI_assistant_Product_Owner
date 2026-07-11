import { create } from 'zustand'
import type { ChatAttachment, ChatMessage, ChatThread } from './model'
import { mockMessagesByThreadId, mockThreads } from './model'

type SendMessageContext = {
  bucketId: string
  bucketName: string
}

type ThreadContext = {
  bucketId?: string
  bucketIds: string[]
  documentIds: string[]
  modelId?: string
  approach?: string
}

type ChatStore = {
  activeThreadId: string
  composerValue: string
  messagesByThreadId: Record<string, ChatMessage[]>
  threads: ChatThread[]
  createThread: () => void
  addAttachmentMessage: (attachment: ChatAttachment) => void
  addAssistantMessage: (message: ChatMessage) => void
  addUserMessage: (text: string, context: SendMessageContext) => void
  upsertThread: (thread: ChatThread) => void
  selectThread: (threadId: string) => void
  setComposerValue: (value: string) => void
  setThreadMessages: (threadId: string, messages: ChatMessage[]) => void
  setThreads: (threads: ChatThread[]) => void
  setThreadContext: (threadId: string, context: ThreadContext) => void
  setThreadSessionId: (threadId: string, sessionId: string) => void
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
    const newThread: ChatThread = {
      id: threadId,
      title: 'Новый чат',
      updatedAt: 'Только что',
      bucketId: '',
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

  addAssistantMessage: (message: ChatMessage) => {
    const { activeThreadId } = get()
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
              updatedAt: 'Только что',
            }
          : thread,
      ),
    }))
  },

  addUserMessage: (text: string, context: SendMessageContext) => {
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

    set((state) => ({
      composerValue: '',
      messagesByThreadId: {
        ...state.messagesByThreadId,
        [activeThreadId]: [
          ...(state.messagesByThreadId[activeThreadId] ?? []),
          userMessage,
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

  selectThread: (threadId: string) => {
    set({
      activeThreadId: threadId,
      composerValue: '',
    })
  },

  upsertThread: (thread: ChatThread) => {
    set((state) => {
      const existingThread = state.threads.find((current) => current.id === thread.id)
      return {
        activeThreadId: thread.id,
        composerValue: '',
        messagesByThreadId: {
          ...state.messagesByThreadId,
          [thread.id]: state.messagesByThreadId[thread.id] ?? [],
        },
        threads: existingThread
          ? state.threads.map((current) => (current.id === thread.id ? thread : current))
          : [thread, ...state.threads],
      }
    })
  },

  setComposerValue: (value: string) => {
    set({ composerValue: value })
  },

  setThreadMessages: (threadId: string, messages: ChatMessage[]) => {
    set((state) => ({
      messagesByThreadId: {
        ...state.messagesByThreadId,
        [threadId]: mergeWithLocalAttachmentMessages(
          state.messagesByThreadId[threadId] ?? [],
          messages,
        ),
      },
    }))
  },

  setThreads: (threads: ChatThread[]) => {
    set((state) => {
      const activeThreadStillExists = threads.some((thread) => thread.id === state.activeThreadId)
      const activeThreadId = activeThreadStillExists
        ? state.activeThreadId
        : (threads[0]?.id ?? state.activeThreadId)
      return {
        activeThreadId,
        messagesByThreadId: {
          ...Object.fromEntries(threads.map((thread) => [thread.id, state.messagesByThreadId[thread.id] ?? []])),
          ...state.messagesByThreadId,
        },
        threads,
      }
    })
  },

  setThreadContext: (threadId: string, context: ThreadContext) => {
    set((state) => ({
      threads: state.threads.map((thread) =>
        thread.id === threadId
          ? {
              ...thread,
              ...context,
            }
          : thread,
      ),
    }))
  },

  setThreadSessionId: (threadId: string, sessionId: string) => {
    set((state) => ({
      threads: state.threads.map((thread) =>
        thread.id === threadId
          ? {
              ...thread,
              sessionId,
            }
          : thread,
      ),
    }))
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

function mergeWithLocalAttachmentMessages(
  localMessages: ChatMessage[],
  serverMessages: ChatMessage[],
): ChatMessage[] {
  const serverIds = new Set(serverMessages.map((message) => message.id))
  const localAttachmentMessages = localMessages.filter(
    (message) => message.attachments?.length && !serverIds.has(message.id),
  )
  return [...localAttachmentMessages, ...serverMessages]
}
