import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import {
  createChatSession,
  deleteChatSession,
  fetchChatMessages,
  fetchChatSessions,
  updateChatSession,
} from '../../entities/chat/api'
import type { ChatThread } from '../../entities/chat/model'
import { useChatStore } from '../../entities/chat/store'
import type { ModelApproach } from '../../entities/model/model'

type UseChatSessionsOptions = {
  activeThreadId: string
  approach: ModelApproach
  isAuthenticated: boolean
  isSendingMessage: boolean
  modelId: string
  selectedBucketId: string
  sessionId?: string
  tenantId?: string
  userId?: string
}

export function useChatSessions({
  activeThreadId,
  approach,
  isAuthenticated,
  isSendingMessage,
  modelId,
  selectedBucketId,
  sessionId,
  tenantId,
  userId,
}: UseChatSessionsOptions) {
  const queryClient = useQueryClient()
  const { deleteThread, setThreadMessages, setThreads, upsertThread } = useChatStore()
  const chatSessionsQuery = useQuery({
    enabled: isAuthenticated,
    queryKey: ['chat-sessions', tenantId, userId],
    queryFn: () => fetchChatSessions(),
    retry: false,
  })
  const chatMessagesQuery = useQuery({
    enabled: isAuthenticated && Boolean(sessionId),
    queryKey: ['chat-messages', tenantId, userId, sessionId],
    queryFn: () => fetchChatMessages(sessionId!),
    retry: false,
  })
  const createSession = useMutation({
    mutationFn: () =>
      createChatSession({
        title: 'Новый чат',
        activeBucketId: selectedBucketId,
        modelId,
        approach,
      }),
    onSuccess: (thread) => {
      upsertThread(thread)
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
    },
    onError: () => {
      useChatStore.getState().createThread()
    },
  })
  const updateSession = useMutation({
    mutationFn: ({
      activeBucketId,
      approach: nextApproach,
      modelId: nextModelId,
      sessionId: nextSessionId,
      title,
    }: {
      activeBucketId?: string
      approach?: ModelApproach
      modelId?: string
      sessionId: string
      title?: string
    }) =>
      updateChatSession(nextSessionId, {
        activeBucketId,
        approach: nextApproach,
        modelId: nextModelId,
        title,
      }),
    onSuccess: (thread) => {
      upsertThread(thread)
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
    },
  })
  const deleteSession = useMutation({
    mutationFn: (nextSessionId: string) => deleteChatSession(nextSessionId),
    onSuccess: (_result, nextSessionId) => {
      deleteThread(nextSessionId)
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
    },
  })

  useEffect(() => {
    if (chatSessionsQuery.data?.length) {
      setThreads(chatSessionsQuery.data)
    }
  }, [chatSessionsQuery.data, setThreads])

  useEffect(() => {
    if (isSendingMessage) {
      return
    }
    if (sessionId && chatMessagesQuery.data) {
      setThreadMessages(activeThreadId, chatMessagesQuery.data)
    }
  }, [
    activeThreadId,
    chatMessagesQuery.data,
    isSendingMessage,
    sessionId,
    setThreadMessages,
  ])

  return {
    createSession: () => createSession.mutate(),
    createSessionAsync: () => createSession.mutateAsync(),
    deleteSession: (nextSessionId: string) => deleteSession.mutateAsync(nextSessionId),
    messagesRevision: chatMessagesQuery.data,
    updateSession: (payload: {
      activeBucketId?: string
      approach?: ModelApproach
      modelId?: string
      sessionId: string
      title?: string
    }) => updateSession.mutate(payload),
    updateSessionAsync: (payload: {
      activeBucketId?: string
      approach?: ModelApproach
      modelId?: string
      sessionId: string
      title?: string
    }) => updateSession.mutateAsync(payload),
  }
}

export type { ChatThread }
