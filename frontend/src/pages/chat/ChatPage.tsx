import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useChatStore } from '../../entities/chat/store'
import type { ChatMode } from '../../entities/chat/model'
import { fetchProviderCatalog } from '../../entities/model/api'
import {
  isModelApproach,
  modelsForApproach,
  normalizeApproach,
  type ModelApproach,
} from '../../entities/model/model'
import { useAuthStore } from '../../entities/user/store'
import { useWorkspaceStore } from '../../entities/workspace/store'
import { useAttachChatDocument } from '../../features/attach-document'
import { useBucketLibrary } from '../../features/bucket-library'
import { useChatSessions } from '../../features/chat-session'
import { useSendChatMessage } from '../../features/send-message'
import { GRAFANA_URL } from '../../shared/config/env'
import { BucketWorkspace } from '../../widgets/bucket-workspace/BucketWorkspace'
import { ChatSidebar } from '../../widgets/chat-sidebar/ChatSidebar'
import { ChatWorkspace } from '../../widgets/chat-workspace/ChatWorkspace'
import { TopBar } from '../../widgets/top-bar/TopBar'

export function ChatPage() {
  const {
    activeThreadId,
    composerValue,
    deleteThread,
    messagesByThreadId,
    renameThread,
    selectThread,
    setComposerValue,
    setThreadContext,
    threads,
    updateAttachmentStatuses,
  } = useChatStore()
  const { currentUser, login, logout, status } = useAuthStore()
  const isAuthenticated = status === 'authenticated' && Boolean(currentUser)
  const {
    activeBucketId,
    activeView,
    openBuckets,
    openChat,
    selectApproach,
    selectChatMode,
    selectBucket,
    selectBucketAndOpenChat,
    selectModel,
    selectedApproach,
    selectedChatMode,
    selectedModelId,
  } = useWorkspaceStore()
  const library = useBucketLibrary({
    isAuthenticated,
    roles: currentUser?.roles,
    selectedBucketId: activeBucketId,
    selectBucket,
    tenantId: currentUser?.tenantId,
    userId: currentUser?.id,
  })
  const selectedBucketId = library.buckets.some((bucket) => bucket.id === activeBucketId)
    ? activeBucketId
    : ''
  const activeBucket = library.buckets.find((bucket) => bucket.id === selectedBucketId)
  const healthQuery = useQuery({
    enabled: isAuthenticated,
    queryKey: ['provider-catalog'],
    queryFn: () => fetchProviderCatalog(),
    retry: false,
    staleTime: 60_000,
  })
  const approachModels = modelsForApproach(selectedApproach, healthQuery.data)
  const selectedModel =
    approachModels.find((model) => model.id === selectedModelId) ?? approachModels[0]
  const effectiveModelId = selectedModel?.id ?? selectedModelId
  const messages = messagesByThreadId[activeThreadId] ?? []
  const activeThread = threads.find((thread) => thread.id === activeThreadId)
  const { attachFile } = useAttachChatDocument({
    approach: selectedApproach,
    modelId: effectiveModelId,
    selectedBucketId,
    sessionId: activeThread?.sessionId,
    tenantId: currentUser?.tenantId,
    userId: currentUser?.id,
  })
  const { isSending, sendMessage } = useSendChatMessage({
    activeBucketId: activeBucket?.id ?? '',
    activeBucketName: activeBucket?.name ?? 'Без bucket',
    activeThreadId,
    approach: selectedApproach,
    chatMode: selectedChatMode,
    composerValue,
    context: {
      selectedBucketId,
      hasBackendBuckets: library.hasBackendBuckets,
      documents: library.documents,
      availableDocuments: library.availableDocuments,
      attachments: messages.flatMap((item) => item.attachments ?? []),
      sessionDocumentIds: activeThread?.documentIds ?? [],
    },
    modelId: effectiveModelId,
    sessionId: activeThread?.sessionId,
    tenantId: currentUser?.tenantId ?? '',
    userId: currentUser?.id,
  })
  const sessions = useChatSessions({
    activeThreadId,
    approach: selectedApproach,
    isAuthenticated,
    isSendingMessage: isSending,
    modelId: effectiveModelId,
    selectedBucketId,
    sessionId: activeThread?.sessionId,
    tenantId: currentUser?.tenantId,
    userId: currentUser?.id,
  })

  useEffect(() => {
    if (!isAuthenticated && activeView === 'buckets') {
      openChat()
    }
  }, [activeView, isAuthenticated, openChat])

  useEffect(() => {
    if (!library.availableDocuments.length) {
      return
    }
    updateAttachmentStatuses(
      library.availableDocuments.map((document) => ({
        id: document.id,
        fileName: document.fileName,
        sourceType: document.sourceType,
        status: document.status,
      })),
    )
  }, [library.availableDocuments, sessions.messagesRevision, updateAttachmentStatuses])

  useEffect(() => {
    if (!activeThread) {
      return
    }
    if (activeThread.bucketId !== activeBucketId) {
      selectBucket(activeThread.bucketId)
    }
    if (activeThread.modelId && activeThread.modelId !== selectedModelId) {
      selectModel(activeThread.modelId)
    }
    if (isModelApproach(activeThread.approach)) {
      const nextApproach = normalizeApproach(activeThread.approach)
      if (nextApproach !== selectedApproach) {
        selectApproach(nextApproach)
      }
    }
  }, [
    activeBucketId,
    activeThread,
    selectApproach,
    selectBucket,
    selectedApproach,
    selectedModelId,
    selectModel,
  ])

  function syncActiveSessionContext(next: {
    activeBucketId?: string
    approach?: ModelApproach
    modelId?: string
  }) {
    if (!activeThread?.sessionId) {
      return
    }
    sessions.updateSession({
      activeBucketId: next.activeBucketId ?? selectedBucketId,
      approach: next.approach ?? selectedApproach,
      modelId: next.modelId ?? selectedModelId,
      sessionId: activeThread.sessionId,
    })
  }

  function handleChangeBucket(bucketId: string) {
    setThreadContext(activeThreadId, {
      bucketId,
      bucketIds: bucketId ? [bucketId] : [],
      documentIds: [],
      modelId: selectedModelId,
      approach: selectedApproach,
    })
    selectBucket(bucketId)
    syncActiveSessionContext({ activeBucketId: bucketId })
  }

  function handleChangeModel(modelId: string) {
    setThreadContext(activeThreadId, {
      bucketId: selectedBucketId,
      bucketIds: selectedBucketId ? [selectedBucketId] : [],
      documentIds: [],
      modelId,
      approach: selectedApproach,
    })
    selectModel(modelId)
    syncActiveSessionContext({ modelId })
  }

  function handleChangeApproach(approach: ModelApproach) {
    const nextModels = modelsForApproach(approach, healthQuery.data)
    const nextModelId = nextModels.some((model) => model.id === selectedModelId)
      ? selectedModelId
      : nextModels[0]?.id ?? selectedModelId
    setThreadContext(activeThreadId, {
      bucketId: selectedBucketId,
      bucketIds: selectedBucketId ? [selectedBucketId] : [],
      documentIds: [],
      modelId: nextModelId,
      approach,
    })
    selectApproach(approach)
    if (nextModelId !== selectedModelId) {
      selectModel(nextModelId)
    }
    syncActiveSessionContext({ approach, modelId: nextModelId })
  }

  function handleSelectBucketFromCard(bucketId: string) {
    setThreadContext(activeThreadId, {
      bucketId,
      bucketIds: [bucketId],
      documentIds: [],
      modelId: effectiveModelId,
      approach: selectedApproach,
    })
    selectBucketAndOpenChat(bucketId)
    syncActiveSessionContext({ activeBucketId: bucketId })
  }

  function handleChangeChatMode(mode: ChatMode) {
    selectChatMode(mode)
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <ChatSidebar
        activeThreadId={activeThreadId}
        onCreateThread={() => sessions.createSession()}
        onDeleteThread={async (threadId) => {
          const thread = threads.find((item) => item.id === threadId)
          if (thread?.sessionId) {
            await sessions.deleteSession(thread.sessionId)
          } else {
            deleteThread(threadId)
          }
          if (useChatStore.getState().threads.length === 0) {
            sessions.createSession()
          }
        }}
        onRenameThread={async (threadId, title) => {
          const thread = threads.find((item) => item.id === threadId)
          renameThread(threadId, title)
          if (thread?.sessionId) {
            await sessions.updateSessionAsync({
              sessionId: thread.sessionId,
              title,
              activeBucketId: thread.bucketId,
              approach: isModelApproach(thread.approach)
                ? normalizeApproach(thread.approach)
                : selectedApproach,
              modelId: thread.modelId ?? selectedModelId,
            })
          }
        }}
        onSelectThread={selectThread}
        threads={threads}
      />
      <section className="flex min-w-0 flex-1 flex-col">
        <TopBar
          activeBucketId={selectedBucketId}
          activeView={isAuthenticated ? activeView : 'chat'}
          buckets={library.buckets}
          grafanaUrl={GRAFANA_URL}
          models={approachModels}
          onChangeApproach={handleChangeApproach}
          onChangeChatMode={handleChangeChatMode}
          onChangeBucket={handleChangeBucket}
          onChangeModel={handleChangeModel}
          onChangeView={(view) => {
            if (view === 'chat' || !isAuthenticated) {
              openChat()
              return
            }
            openBuckets()
          }}
          onLoginClick={() => login()}
          onLogoutClick={() => { void logout() }}
          onOpenObservability={() => {
            window.open(GRAFANA_URL, '_blank', 'noopener,noreferrer')
          }}
          selectedApproach={selectedApproach}
          selectedChatMode={selectedChatMode}
          selectedModelId={effectiveModelId}
          user={currentUser}
        />

        {activeView === 'chat' || !isAuthenticated ? (
          <ChatWorkspace
            activeBucket={activeBucket}
            approach={selectedApproach}
            chatMode={selectedChatMode}
            composerValue={composerValue}
            isSending={isSending}
            messages={messages}
            onAttachFile={(file) => {
              void attachFile(file)
            }}
            onChangeComposerValue={setComposerValue}
            onSendMessage={sendMessage}
            selectedModel={selectedModel}
          />
        ) : (
          <BucketWorkspace
            availableDocuments={library.availableDocuments}
            buckets={library.buckets}
            canMutateDocuments={library.hasBackendBuckets}
            currentUserId={currentUser!.id}
            documents={library.documents}
            onCancelStagedDocument={library.cancelStagedDocument}
            onCommitChanges={async (bucketId, changes) => {
              await library.commitBucketChanges(bucketId, changes)
            }}
            onCreateBucket={library.createBucket}
            onDeleteBucket={library.deleteBucket}
            onDeleteDocument={library.deleteLibraryDocument}
            onDownloadDocuments={library.downloadDocuments}
            onInspectBucket={library.setInspectedBucketId}
            onRetryIndexing={async (documentId, bucketId) => {
              await library.retryIndexing(documentId, bucketId)
            }}
            onSelectBucket={handleSelectBucketFromCard}
            onStageDocument={library.stageDocument}
            onUpdateBucket={async (bucketId, payload) => {
              await library.updateBucket(bucketId, payload)
            }}
          />
        )}
      </section>
    </div>
  )
}
