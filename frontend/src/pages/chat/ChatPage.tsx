import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchBuckets } from '../../entities/bucket/api'
import { mockBuckets } from '../../entities/bucket/model'
import { useChatStore } from '../../entities/chat/store'
import {
  addDocumentToBucket,
  fetchAvailableDocuments,
  fetchBucketDocuments,
  uploadDocument,
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
    composerValue,
    createThread,
    messagesByThreadId,
    selectThread,
    sendMessage,
    setComposerValue,
    threads,
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
    retry: false,
  })
  const documents = documentsQuery.data ?? mockDocuments
  const availableDocumentsQuery = useQuery({
    enabled: hasBackendBuckets,
    queryKey: ['documents-available', userForApi.tenantId, userForApi.id, userForApi.roles],
    queryFn: () => fetchAvailableDocuments(userForApi),
    retry: false,
  })
  const availableDocuments = availableDocumentsQuery.data ?? mockDocuments
  const addDocumentMutation = useMutation({
    mutationFn: ({ bucketId, documentId }: { bucketId: string; documentId: string }) =>
      addDocumentToBucket(userForApi, bucketId, documentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['bucket-documents'] })
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
    },
  })
  const uploadDocumentMutation = useMutation({
    mutationFn: ({ bucketId, file }: { bucketId: string; file: File }) =>
      uploadDocument(userForApi, bucketId, file, 'private'),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['bucket-documents'] })
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
    },
  })

  function handleSendMessage() {
    sendMessage(composerValue, {
      bucketId: activeBucket?.id ?? selectedBucketId,
      bucketName: activeBucket?.name ?? 'Selected bucket',
    })
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
            onChangeComposerValue={setComposerValue}
            onSendMessage={handleSendMessage}
            selectedModel={selectedModel}
          />
        ) : (
          <BucketWorkspace
            availableDocuments={availableDocuments}
            buckets={buckets}
            documents={documents}
            onAddDocumentToBucket={(bucketId, documentId) =>
              addDocumentMutation.mutate({ bucketId, documentId })
            }
            onCreateBucket={() => undefined}
            onInspectBucket={selectBucket}
            onSelectBucket={selectBucketAndOpenChat}
            onUploadDocument={(bucketId, file) => uploadDocumentMutation.mutate({ bucketId, file })}
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
