import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createChatSession, saveChatAttachmentMessage } from '../../entities/chat/api'
import { useChatStore } from '../../entities/chat/store'
import { commitPersonalDocuments, stageDocument } from '../../entities/document/api'
import type { ModelApproach } from '../../entities/model/model'

type UseAttachChatDocumentOptions = {
  approach: ModelApproach
  modelId: string
  selectedBucketId: string
  sessionId?: string
  tenantId?: string
  userId?: string
}

export function useAttachChatDocument({
  approach,
  modelId,
  selectedBucketId,
  sessionId,
  tenantId,
  userId,
}: UseAttachChatDocumentOptions) {
  const queryClient = useQueryClient()
  const { addAttachmentMessage, upsertThread } = useChatStore()
  const stageDocumentMutation = useMutation({
    mutationFn: (file: File) => stageDocument(file),
  })
  const commitPersonalDocumentsMutation = useMutation({
    mutationFn: ({ stagedUploadIds }: { stagedUploadIds: string[] }) =>
      commitPersonalDocuments({
        stagedUploadIds,
        visibility: 'private',
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
    },
  })

  async function attachFile(file: File) {
    try {
      let nextSessionId = sessionId
      if (!nextSessionId) {
        const thread = await createChatSession({
          title: 'Новый чат',
          activeBucketId: selectedBucketId,
          modelId,
          approach,
        })
        upsertThread(thread)
        nextSessionId = thread.sessionId ?? thread.id
        void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      }

      const stagedDocument = await stageDocumentMutation.mutateAsync(file)
      const documents = await commitPersonalDocumentsMutation.mutateAsync({
        stagedUploadIds: [stagedDocument.id],
      })
      const document = documents[0]
      const attachment = {
        id: document?.id ?? stagedDocument.id,
        fileName: document?.fileName ?? stagedDocument.fileName,
        sourceType: document?.sourceType ?? stagedDocument.sourceType,
        status: document?.status ?? 'indexing' as const,
      }
      const savedMessage = await saveChatAttachmentMessage(nextSessionId, {
        documentId: attachment.id,
        fileName: attachment.fileName,
        sourceType: attachment.sourceType,
        status: attachment.status,
      })
      addAttachmentMessage(attachment, savedMessage.id)
      void queryClient.invalidateQueries({
        queryKey: ['chat-messages', tenantId, userId, nextSessionId],
      })
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
    } catch (error) {
      window.alert(error instanceof Error ? error.message : 'Не удалось загрузить документ.')
    }
  }

  return { attachFile }
}
