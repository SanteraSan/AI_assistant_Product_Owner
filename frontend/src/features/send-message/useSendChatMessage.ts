import { useMutation, useQueryClient } from '@tanstack/react-query'
import { sendAgentMessage, sendRagMessage } from '../../entities/chat/api'
import type { ChatMode } from '../../entities/chat/model'
import { useChatStore } from '../../entities/chat/store'
import type { ModelApproach } from '../../entities/model/model'
import { formatApiError } from '../../shared/api/httpClient'
import { resolveChatContext, type ResolveChatContextInput } from '../chat-context'

type UseSendChatMessageOptions = {
  activeBucketId: string
  activeBucketName: string
  activeThreadId: string
  approach: ModelApproach
  chatMode: ChatMode
  composerValue: string
  context: Omit<ResolveChatContextInput, 'message'>
  modelId: string
  sessionId?: string
  tenantId: string
  userId?: string
}

export function useSendChatMessage({
  activeBucketId,
  activeBucketName,
  activeThreadId,
  approach,
  chatMode,
  composerValue,
  context,
  modelId,
  sessionId,
  tenantId,
  userId,
}: UseSendChatMessageOptions) {
  const queryClient = useQueryClient()
  const { addAssistantMessage, addUserMessage, setThreadContext, setThreadSessionId } = useChatStore()

  function onSuccess(result: { message: Parameters<typeof addAssistantMessage>[0]; sessionId?: string }) {
    addAssistantMessage(result.message)
    if (result.sessionId) {
      setThreadSessionId(activeThreadId, result.sessionId)
      void queryClient.invalidateQueries({
        queryKey: ['chat-messages', tenantId, userId, result.sessionId],
      })
    }
    void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
  }

  const sendRagMessageMutation = useMutation({
    mutationFn: (message: string) =>
      sendRagMessage({
        message,
        model: modelId,
        approach,
        activeBucketId,
        sessionId,
        tenantId,
        ...resolveChatContext({ ...context, message }),
      }),
    onSuccess,
    onError: (error) => {
      addAssistantMessage({
        id: `assistant-error-${Date.now()}`,
        role: 'assistant',
        content: formatApiError(error, 'Не удалось получить ответ от RAG.'),
      })
    },
  })
  const sendAgentMessageMutation = useMutation({
    mutationFn: (message: string) =>
      sendAgentMessage({
        message,
        model: modelId,
        approach,
        activeBucketId,
        sessionId,
        tenantId,
        ...resolveChatContext({ ...context, message }),
      }),
    onSuccess,
    onError: (error) => {
      addAssistantMessage({
        id: `assistant-error-${Date.now()}`,
        role: 'assistant',
        content: formatApiError(error, 'Не удалось получить ответ агента.'),
      })
    },
  })
  const isSending = sendRagMessageMutation.isPending || sendAgentMessageMutation.isPending

  function sendMessage() {
    const message = composerValue.trim()
    if (!message || isSending) {
      return
    }
    const nextContext = resolveChatContext({ ...context, message })
    addUserMessage(message, {
      bucketId: activeBucketId,
      bucketName: activeBucketName,
    })
    setThreadContext(activeThreadId, {
      bucketIds: nextContext.bucketIds,
      documentIds: nextContext.documentIds,
      modelId,
      approach,
    })
    if (chatMode === 'agent') {
      sendAgentMessageMutation.mutate(message)
      return
    }
    sendRagMessageMutation.mutate(message)
  }

  return { isSending, sendMessage }
}
