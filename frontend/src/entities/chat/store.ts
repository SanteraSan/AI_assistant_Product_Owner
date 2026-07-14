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
  addAttachmentMessage: (attachment: ChatAttachment, messageId?: string) => void
  addAssistantMessage: (message: ChatMessage) => void
  addUserMessage: (text: string, context: SendMessageContext) => void
  upsertThread: (thread: ChatThread) => void
  selectThread: (threadId: string) => void
  setComposerValue: (value: string) => void
  setThreadMessages: (threadId: string, messages: ChatMessage[]) => void
  setThreads: (threads: ChatThread[]) => void
  setThreadContext: (threadId: string, context: ThreadContext) => void
  setThreadSessionId: (threadId: string, sessionId: string) => void
  renameThread: (threadId: string, title: string) => void
  deleteThread: (threadId: string) => void
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

  addAttachmentMessage: (attachment: ChatAttachment, messageId?: string) => {
    const { activeThreadId } = get()
    const message: ChatMessage = {
      id: messageId ?? `attachment-${Date.now()}`,
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
              documentIds: Array.from(
                new Set([...(thread.documentIds ?? []), attachment.id]),
              ),
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
    set((state) => {
      const mergedMessages = mergeWithLocalOptimisticMessages(
        state.messagesByThreadId[threadId] ?? [],
        messages,
      )
      const attachmentDocumentIds = mergedMessages
        .flatMap((message) => message.attachments ?? [])
        .map((attachment) => attachment.id)
        .filter(Boolean)
      return {
        messagesByThreadId: {
          ...state.messagesByThreadId,
          [threadId]: mergedMessages,
        },
        threads: state.threads.map((thread) =>
          thread.id === threadId && attachmentDocumentIds.length
            ? {
                ...thread,
                documentIds: Array.from(
                  new Set([...(thread.documentIds ?? []), ...attachmentDocumentIds]),
                ),
              }
            : thread,
        ),
      }
    })
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

  renameThread: (threadId: string, title: string) => {
    const nextTitle = title.trim() || 'Новый чат'
    set((state) => ({
      threads: state.threads.map((thread) =>
        thread.id === threadId
          ? {
              ...thread,
              title: nextTitle,
              updatedAt: 'Только что',
            }
          : thread,
      ),
    }))
  },

  deleteThread: (threadId: string) => {
    set((state) => {
      const remainingThreads = state.threads.filter((thread) => thread.id !== threadId)
      const nextMessages = { ...state.messagesByThreadId }
      delete nextMessages[threadId]
      const nextActiveThreadId =
        state.activeThreadId === threadId
          ? (remainingThreads[0]?.id ?? '')
          : state.activeThreadId
      return {
        activeThreadId: nextActiveThreadId,
        messagesByThreadId: nextMessages,
        threads: remainingThreads,
      }
    })
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

function mergeWithLocalOptimisticMessages(
  localMessages: ChatMessage[],
  serverMessages: ChatMessage[],
): ChatMessage[] {
  const serverIds = new Set(serverMessages.map((message) => message.id))
  const serverFingerprints = new Set(
    serverMessages.map((message) => messageFingerprint(message)),
  )

  const pendingLocalMessages = localMessages.filter((message) => {
    if (serverIds.has(message.id) || serverFingerprints.has(messageFingerprint(message))) {
      return false
    }
    if (message.attachments?.length) {
      return true
    }
    return (
      message.id.startsWith('user-') ||
      message.id.startsWith('attachment-') ||
      message.id.startsWith('assistant-error-') ||
      message.role === 'assistant'
    )
  })

  return [...serverMessages, ...pendingLocalMessages]
}

function messageFingerprint(message: ChatMessage): string {
  return `${message.role}:${message.content.trim()}`
}
