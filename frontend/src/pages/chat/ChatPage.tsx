import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { createBucket, fetchBuckets } from '../../entities/bucket/api'
import { mockBuckets } from '../../entities/bucket/model'
import { useChatStore } from '../../entities/chat/store'
import {
  cancelStagedDocument,
  commitBucketDocuments,
  commitPersonalDocuments,
  fetchAvailableDocuments,
  fetchBucketDocuments,
  stageDocument,
} from '../../entities/document/api'
import { mockDocuments } from '../../entities/document/model'
import { localModels } from '../../entities/model/model'
import { mockUser } from '../../entities/user/model'
import { useAuthStore } from '../../entities/user/store'
import { useWorkspaceStore } from '../../entities/workspace/store'
import { MockLoginModal } from '../../features/mock-login/MockLoginModal'
import { useUiStore } from '../../shared/ui/store'
import { BucketWorkspace } from '../../widgets/bucket-workspace/BucketWorkspace'
import { ChatSidebar } from '../../widgets/chat-sidebar/ChatSidebar'
import { ChatWorkspace } from '../../widgets/chat-workspace/ChatWorkspace'
import { TopBar } from '../../widgets/top-bar/TopBar'

export function ChatPage() {
  const queryClient = useQueryClient()
  const {
    activeThreadId,
    addAttachmentMessage,
    composerValue,
    createThread,
    messagesByThreadId,
    selectThread,
    sendMessage,
    setComposerValue,
    threads,
    updateAttachmentStatuses,
  } = useChatStore()
  const { currentUser, loginAsMockUser } = useAuthStore()
  const {
    activeBucketId,
    activeView,
    openBuckets,
    openChat,
    selectApproach,
    selectBucket,
    selectBucketAndOpenChat,
    selectModel,
    selectedApproach,
    selectedModelId,
  } = useWorkspaceStore()
  const { closeLoginModal, isLoginModalOpen, openLoginModal } = useUiStore()
  const userForApi = currentUser ?? mockUser
  const bucketsQuery = useQuery({
    queryKey: ['buckets', userForApi.tenantId],
    queryFn: () => fetchBuckets(userForApi),
    retry: false,
  })
  const hasBackendBuckets = Boolean(bucketsQuery.data?.length)
  const buckets = hasBackendBuckets ? bucketsQuery.data! : mockBuckets

  const selectedBucketId = buckets.some((bucket) => bucket.id === activeBucketId)
    ? activeBucketId
    : (buckets[0]?.id ?? '')
  const activeBucket = buckets.find((bucket) => bucket.id === selectedBucketId) ?? buckets[0]
  const selectedModel = localModels.find((model) => model.id === selectedModelId)
  const messages = messagesByThreadId[activeThreadId] ?? []
  const documentsQuery = useQuery({
    enabled: hasBackendBuckets && Boolean(selectedBucketId),
    queryKey: ['bucket-documents', userForApi.tenantId, selectedBucketId],
    queryFn: () => fetchBucketDocuments(userForApi, selectedBucketId),
    refetchInterval: (query) =>
      query.state.data?.some((document) => document.status === 'indexing')
        ? 3000
        : false,
    retry: false,
  })
  const documents = hasBackendBuckets ? (documentsQuery.data ?? []) : mockDocuments
  const availableDocumentsQuery = useQuery({
    enabled: hasBackendBuckets,
    queryKey: ['documents-available', userForApi.tenantId, userForApi.id, userForApi.roles],
    queryFn: () => fetchAvailableDocuments(userForApi),
    refetchInterval: (query) =>
      query.state.data?.some((document) => document.status === 'indexing') ? 3000 : false,
    retry: false,
  })
  const availableDocuments = hasBackendBuckets ? (availableDocumentsQuery.data ?? []) : mockDocuments
  const stageDocumentMutation = useMutation({
    mutationFn: (file: File) => stageDocument(userForApi, file),
  })
  const cancelStagedDocumentMutation = useMutation({
    mutationFn: (uploadId: string) => cancelStagedDocument(userForApi, uploadId),
  })
  const commitBucketDocumentsMutation = useMutation({
    mutationFn: ({
      bucketId,
      existingDocumentIds,
      removedDocumentIds,
      stagedUploadIds,
    }: {
      bucketId: string
      existingDocumentIds: string[]
      removedDocumentIds: string[]
      stagedUploadIds: string[]
    }) =>
      commitBucketDocuments(userForApi, bucketId, {
        existingDocumentIds,
        removedDocumentIds,
        stagedUploadIds,
        visibility: 'private',
      }),
    onSuccess: (committedDocuments, variables) => {
      queryClient.setQueryData(
        ['bucket-documents', userForApi.tenantId, variables.bucketId],
        (current: typeof committedDocuments | undefined) => {
          const remainingDocuments = (current ?? []).filter(
            (document) => !variables.removedDocumentIds.includes(document.id),
          )
          const committedById = new Map(committedDocuments.map((document) => [document.id, document]))
          const mergedDocuments = remainingDocuments.map((document) =>
            committedById.get(document.id) ?? document,
          )
          for (const document of committedDocuments) {
            if (!mergedDocuments.some((existingDocument) => existingDocument.id === document.id)) {
              mergedDocuments.push(document)
            }
          }
          return mergedDocuments
        },
      )
      void queryClient.invalidateQueries({ queryKey: ['bucket-documents'] })
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
    },
  })
  const commitPersonalDocumentsMutation = useMutation({
    mutationFn: ({ stagedUploadIds }: { stagedUploadIds: string[] }) =>
      commitPersonalDocuments(userForApi, {
        stagedUploadIds,
        visibility: 'private',
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
    },
  })
  const createBucketMutation = useMutation({
    mutationFn: () =>
      createBucket(userForApi, {
        name: `Личная база знаний ${new Date().toLocaleTimeString('ru-RU')}`,
        description: 'Персональный bucket для документов, загруженных через UI.',
      }),
    onSuccess: (bucket) => {
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
      selectBucket(bucket.id)
    },
  })

  useEffect(() => {
    updateAttachmentStatuses(
      availableDocuments.map((document) => ({
        id: document.id,
        fileName: document.fileName,
        sourceType: document.sourceType,
        status: document.status,
      })),
    )
  }, [availableDocuments, updateAttachmentStatuses])

  function handleSendMessage() {
    sendMessage(composerValue, {
      bucketId: activeBucket?.id ?? selectedBucketId,
      bucketName: activeBucket?.name ?? 'Selected bucket',
    })
  }

  async function handleAttachFileToChat(file: File) {
    try {
      const stagedDocument = await stageDocumentMutation.mutateAsync(file)
      const documents = await commitPersonalDocumentsMutation.mutateAsync({
        stagedUploadIds: [stagedDocument.id],
      })
      const document = documents[0]
      addAttachmentMessage({
        id: document?.id ?? stagedDocument.id,
        fileName: document?.fileName ?? stagedDocument.fileName,
        sourceType: document?.sourceType ?? stagedDocument.sourceType,
        status: document?.status ?? 'indexing',
      })
    } catch (error) {
      window.alert(error instanceof Error ? error.message : 'Не удалось загрузить документ.')
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <ChatSidebar
        activeThreadId={activeThreadId}
        onCreateThread={createThread}
        onSelectThread={selectThread}
        threads={threads}
      />
      <section className="flex min-w-0 flex-1 flex-col">
        <TopBar
          activeBucketId={selectedBucketId}
          activeView={activeView}
          buckets={buckets}
          models={localModels}
          onChangeApproach={selectApproach}
          onChangeBucket={selectBucket}
          onChangeModel={selectModel}
          onChangeView={(view) => {
            if (view === 'chat') {
              openChat()
              return
            }
            openBuckets()
          }}
          onLoginClick={openLoginModal}
          selectedApproach={selectedApproach}
          selectedModelId={selectedModelId}
          user={currentUser}
        />

        {activeView === 'chat' ? (
          <ChatWorkspace
            activeBucket={activeBucket}
            approach={selectedApproach}
            composerValue={composerValue}
            messages={messages}
            onAttachFile={(file) => {
              void handleAttachFileToChat(file)
            }}
            onChangeComposerValue={setComposerValue}
            onSendMessage={handleSendMessage}
            selectedModel={selectedModel}
          />
        ) : (
          <BucketWorkspace
            availableDocuments={availableDocuments}
            buckets={buckets}
            canMutateDocuments={hasBackendBuckets}
            documents={documents}
            onCancelStagedDocument={(uploadId) =>
              cancelStagedDocumentMutation.mutateAsync(uploadId)
            }
            onCommitChanges={async (bucketId, changes) => {
              await commitBucketDocumentsMutation.mutateAsync({ bucketId, ...changes })
            }}
            onCreateBucket={() => createBucketMutation.mutate()}
            onInspectBucket={selectBucket}
            onSelectBucket={selectBucketAndOpenChat}
            onStageDocument={(file) => stageDocumentMutation.mutateAsync(file)}
          />
        )}
      </section>

      <MockLoginModal
        isOpen={isLoginModalOpen}
        onClose={closeLoginModal}
        onLogin={loginAsMockUser}
        user={mockUser}
      />
    </div>
  )
}
