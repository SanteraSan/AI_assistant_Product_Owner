import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { createBucket, deleteBucket, fetchBuckets, updateBucket } from '../../entities/bucket/api'
import { mockBuckets } from '../../entities/bucket/model'
import {
  createChatSession,
  deleteChatSession,
  fetchChatMessages,
  fetchChatSessions,
  saveChatAttachmentMessage,
  sendAgentMessage,
  sendRagMessage,
  updateChatSession,
} from '../../entities/chat/api'
import type { ChatMode } from '../../entities/chat/model'
import { useChatStore } from '../../entities/chat/store'
import {
  cancelStagedDocument,
  commitBucketDocuments,
  commitPersonalDocuments,
  deleteDocument,
  DocumentDeleteConflictError,
  fetchAvailableDocuments,
  fetchBucketDocuments,
  downloadBucketDocuments,
  retryDocumentIndexing,
  stageDocument,
} from '../../entities/document/api'
import { mockDocuments } from '../../entities/document/model'
import { fetchProviderCatalog } from '../../entities/model/api'
import {
  isModelApproach,
  modelsForApproach,
  normalizeApproach,
  type ModelApproach,
} from '../../entities/model/model'
import { formatApiError } from '../../shared/api/httpClient'
import { useAuthStore } from '../../entities/user/store'
import { useWorkspaceStore } from '../../entities/workspace/store'
import { BucketWorkspace } from '../../widgets/bucket-workspace/BucketWorkspace'
import { ChatSidebar } from '../../widgets/chat-sidebar/ChatSidebar'
import { ChatWorkspace } from '../../widgets/chat-workspace/ChatWorkspace'
import { TopBar } from '../../widgets/top-bar/TopBar'
import { GRAFANA_URL } from '../../shared/config/env'

export function ChatPage() {
  const queryClient = useQueryClient()
  const [inspectedBucketId, setInspectedBucketId] = useState('')
  const {
    activeThreadId,
    addAttachmentMessage,
    addAssistantMessage,
    addUserMessage,
    composerValue,
    createThread: createLocalThread,
    deleteThread,
    messagesByThreadId,
    renameThread,
    selectThread,
    setComposerValue,
    setThreadMessages,
    setThreads,
    setThreadContext,
    setThreadSessionId,
    threads,
    upsertThread,
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
  const bucketsQuery = useQuery({
    enabled: isAuthenticated,
    queryKey: ['buckets', currentUser?.tenantId],
    queryFn: () => fetchBuckets(),
    retry: false,
  })
  const hasBackendBuckets = Boolean(bucketsQuery.data?.length)
  const buckets = hasBackendBuckets ? bucketsQuery.data! : mockBuckets

  const selectedBucketId = buckets.some((bucket) => bucket.id === activeBucketId)
    ? activeBucketId
    : ''
  const activeBucket = buckets.find((bucket) => bucket.id === selectedBucketId)
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
  const chatSessionsQuery = useQuery({
    enabled: isAuthenticated,
    queryKey: ['chat-sessions', currentUser?.tenantId, currentUser?.id],
    queryFn: () => fetchChatSessions(),
    retry: false,
  })
  const activeSessionId = activeThread?.sessionId
  const chatMessagesQuery = useQuery({
    enabled: isAuthenticated && Boolean(activeSessionId),
    queryKey: ['chat-messages', currentUser?.tenantId, currentUser?.id, activeSessionId],
    queryFn: () => fetchChatMessages(activeSessionId!),
    retry: false,
  })
  const documentsQuery = useQuery({
    enabled: isAuthenticated && hasBackendBuckets && Boolean(inspectedBucketId),
    queryKey: ['bucket-documents', currentUser?.tenantId, inspectedBucketId],
    queryFn: () => fetchBucketDocuments(inspectedBucketId),
    refetchInterval: (query) =>
      query.state.data?.some((document) => document.status === 'indexing')
        ? 3000
        : false,
    retry: false,
  })
  const documents = useMemo(
    () => (hasBackendBuckets ? (documentsQuery.data ?? []) : mockDocuments),
    [documentsQuery.data, hasBackendBuckets],
  )
  const availableDocumentsQuery = useQuery({
    enabled: isAuthenticated && hasBackendBuckets,
    queryKey: ['documents-available', currentUser?.tenantId, currentUser?.id, currentUser?.roles],
    queryFn: () => fetchAvailableDocuments(),
    refetchInterval: (query) =>
      query.state.data?.some((document) => document.status === 'indexing') ? 3000 : false,
    retry: false,
  })
  const availableDocuments = useMemo(
    () => (hasBackendBuckets ? (availableDocumentsQuery.data ?? []) : mockDocuments),
    [availableDocumentsQuery.data, hasBackendBuckets],
  )
  const stageDocumentMutation = useMutation({
    mutationFn: (file: File) => stageDocument(file),
  })
  const cancelStagedDocumentMutation = useMutation({
    mutationFn: (uploadId: string) => cancelStagedDocument(uploadId),
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
      commitBucketDocuments(bucketId, {
        existingDocumentIds,
        removedDocumentIds,
        stagedUploadIds,
        visibility: 'private',
      }),
    onSuccess: (committedDocuments, variables) => {
      queryClient.setQueryData(
        ['bucket-documents', currentUser?.tenantId, variables.bucketId],
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
      commitPersonalDocuments({
        stagedUploadIds,
        visibility: 'private',
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
    },
  })
  const deleteDocumentMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(documentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
      void queryClient.invalidateQueries({ queryKey: ['bucket-documents'] })
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
    },
  })
  const retryDocumentIndexingMutation = useMutation({
    mutationFn: ({
      bucketId,
      documentId,
    }: {
      documentId: string
      bucketId?: string
    }) => retryDocumentIndexing(documentId, bucketId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
      void queryClient.invalidateQueries({ queryKey: ['bucket-documents'] })
    },
  })
  const createBucketMutation = useMutation({
    mutationFn: () =>
      createBucket({
        name: `Личная база знаний ${new Date().toLocaleTimeString('ru-RU')}`,
        description: 'Персональный bucket для документов, загруженных через UI.',
      }),
    onSuccess: (bucket) => {
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
      selectBucket(bucket.id)
    },
  })
  const updateBucketMutation = useMutation({
    mutationFn: ({
      bucketId,
      description,
      name,
    }: {
      bucketId: string
      description: string
      name: string
    }) => updateBucket(bucketId, { name, description }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
    },
  })
  const deleteBucketMutation = useMutation({
    mutationFn: (bucketId: string) => deleteBucket(bucketId),
    onSuccess: (_result, bucketId) => {
      if (selectedBucketId === bucketId) {
        selectBucket('')
      }
      if (inspectedBucketId === bucketId) {
        setInspectedBucketId('')
      }
      void queryClient.invalidateQueries({ queryKey: ['buckets'] })
      void queryClient.invalidateQueries({ queryKey: ['bucket-documents'] })
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
    },
  })
  const createChatSessionMutation = useMutation({
    mutationFn: () =>
      createChatSession({
        title: 'Новый чат',
        activeBucketId: selectedBucketId,
        modelId: effectiveModelId,
        approach: selectedApproach,
      }),
    onSuccess: (thread) => {
      upsertThread(thread)
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
    },
    onError: () => {
      createLocalThread()
    },
  })
  const updateChatSessionMutation = useMutation({
    mutationFn: ({
      activeBucketId,
      approach,
      modelId,
      sessionId,
      title,
    }: {
      activeBucketId?: string
      approach?: ModelApproach
      modelId?: string
      sessionId: string
      title?: string
    }) =>
      updateChatSession(sessionId, {
        activeBucketId,
        approach,
        modelId,
        title,
      }),
    onSuccess: (thread) => {
      upsertThread(thread)
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
    },
  })
  const deleteChatSessionMutation = useMutation({
    mutationFn: (sessionId: string) => deleteChatSession(sessionId),
    onSuccess: (_result, sessionId) => {
      deleteThread(sessionId)
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
    },
  })
  const sendRagMessageMutation = useMutation({
    mutationFn: (message: string) =>
      sendRagMessage({
        message,
        model: effectiveModelId,
        approach: selectedApproach,
        activeBucketId: selectedBucketId,
        sessionId: activeThread?.sessionId,
        tenantId: currentUser!.tenantId,
        ...chatContext(message),
      }),
    onSuccess: ({ message, sessionId }) => {
      addAssistantMessage(message)
      if (sessionId) {
        setThreadSessionId(activeThreadId, sessionId)
      }
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      if (sessionId) {
        void queryClient.invalidateQueries({ queryKey: ['chat-messages', currentUser?.tenantId, currentUser?.id, sessionId] })
      }
    },
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
        model: effectiveModelId,
        approach: selectedApproach,
        activeBucketId: selectedBucketId,
        sessionId: activeThread?.sessionId,
        tenantId: currentUser!.tenantId,
        ...chatContext(message),
      }),
    onSuccess: ({ message, sessionId }) => {
      addAssistantMessage(message)
      if (sessionId) {
        setThreadSessionId(activeThreadId, sessionId)
      }
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      if (sessionId) {
        void queryClient.invalidateQueries({ queryKey: ['chat-messages', currentUser?.tenantId, currentUser?.id, sessionId] })
      }
    },
    onError: (error) => {
      addAssistantMessage({
        id: `assistant-error-${Date.now()}`,
        role: 'assistant',
        content: formatApiError(error, 'Не удалось получить ответ агента.'),
      })
    },
  })
  const isSendingMessage =
    sendRagMessageMutation.isPending || sendAgentMessageMutation.isPending

  useEffect(() => {
    if (chatSessionsQuery.data?.length) {
      setThreads(chatSessionsQuery.data)
    }
  }, [chatSessionsQuery.data, setThreads])

  useEffect(() => {
    if (isSendingMessage) {
      return
    }
    if (activeSessionId && chatMessagesQuery.data) {
      setThreadMessages(activeThreadId, chatMessagesQuery.data)
    }
  }, [
    activeSessionId,
    activeThreadId,
    chatMessagesQuery.data,
    isSendingMessage,
    setThreadMessages,
  ])

  useEffect(() => {
    if (!availableDocuments.length) {
      return
    }
    updateAttachmentStatuses(
      availableDocuments.map((document) => ({
        id: document.id,
        fileName: document.fileName,
        sourceType: document.sourceType,
        status: document.status,
      })),
    )
  }, [availableDocuments, chatMessagesQuery.data, updateAttachmentStatuses])

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

  function selectedBucketIdsForChat(): string[] {
    if (!hasBackendBuckets || !selectedBucketId) {
      return []
    }
    return [selectedBucketId]
  }

  function indexedAttachmentDocumentIds(): string[] {
    const fromMessages = messages
      .flatMap((message) => message.attachments ?? [])
      .filter((attachment) => attachment.status === 'indexed')
      .map((attachment) => attachment.id)
    const indexedAvailableIds = new Set(indexedAvailableDocumentIds())
    const fromSession = (activeThread?.documentIds ?? []).filter((documentId) =>
      indexedAvailableIds.has(documentId),
    )
    return Array.from(new Set([...fromMessages, ...fromSession]))
  }

  function indexedAvailableDocumentIds(): string[] {
    return Array.from(new Set(
      availableDocuments
        .filter((document) => document.status === 'indexed')
        .map((document) => document.id),
    ))
  }

  function namedDocumentIds(message: string): string[] {
    const normalized = normalizeDocumentName(message)
    const candidates = selectedBucketId
      ? [...documents, ...availableDocuments]
      : availableDocuments
    return Array.from(new Set(
      candidates
        .filter((document) => document.status === 'indexed')
        .filter((document) => {
          return documentNameVariants(document.fileName, document.title).some((variant) =>
            normalized.includes(variant),
          )
        })
        .map((document) => document.id),
    ))
  }

  function chatContext(message: string): { bucketIds: string[]; documentIds: string[] } {
    const explicitDocumentIds = namedDocumentIds(message)
    if (explicitDocumentIds.length) {
      return { bucketIds: [], documentIds: explicitDocumentIds }
    }
    if (selectedBucketId && asksSelectedBucketDocuments(message)) {
      return { bucketIds: selectedBucketIdsForChat(), documentIds: [] }
    }
    const attachmentDocumentIds = indexedAttachmentDocumentIds()
    if (attachmentDocumentIds.length) {
      return { bucketIds: [], documentIds: [attachmentDocumentIds[attachmentDocumentIds.length - 1]] }
    }
    if (asksAllAvailableDocuments(message) || !selectedBucketId) {
      return { bucketIds: [], documentIds: indexedAvailableDocumentIds() }
    }
    return { bucketIds: selectedBucketIdsForChat(), documentIds: [] }
  }

  function handleSendMessage() {
    const message = composerValue.trim()
    if (!message || isSendingMessage) {
      return
    }
    const { bucketIds, documentIds } = chatContext(message)
    addUserMessage(message, {
      bucketId: activeBucket?.id ?? '',
      bucketName: activeBucket?.name ?? 'Без bucket',
    })
    setThreadContext(activeThreadId, {
      bucketIds,
      documentIds,
      modelId: effectiveModelId,
      approach: selectedApproach,
    })
    if (selectedChatMode === 'agent') {
      sendAgentMessageMutation.mutate(message)
      return
    }
    sendRagMessageMutation.mutate(message)
  }

  function handleChangeChatMode(mode: ChatMode) {
    selectChatMode(mode)
  }

  async function handleAttachFileToChat(file: File) {
    try {
      let sessionId = activeThread?.sessionId
      if (!sessionId) {
        const thread = await createChatSession({
          title: 'Новый чат',
          activeBucketId: selectedBucketId,
          modelId: effectiveModelId,
          approach: selectedApproach,
        })
        upsertThread(thread)
        sessionId = thread.sessionId ?? thread.id
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
        status: document?.status ?? 'indexing',
      }
      const savedMessage = await saveChatAttachmentMessage(sessionId, {
        documentId: attachment.id,
        fileName: attachment.fileName,
        sourceType: attachment.sourceType,
        status: attachment.status,
      })
      addAttachmentMessage(attachment, savedMessage.id)
      void queryClient.invalidateQueries({
        queryKey: ['chat-messages', currentUser?.tenantId, currentUser?.id, sessionId],
      })
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      void queryClient.invalidateQueries({ queryKey: ['documents-available'] })
    } catch (error) {
      window.alert(error instanceof Error ? error.message : 'Не удалось загрузить документ.')
    }
  }

  function syncActiveSessionContext(next: {
    activeBucketId?: string
    approach?: ModelApproach
    modelId?: string
  }) {
    if (!activeThread?.sessionId) {
      return
    }
    updateChatSessionMutation.mutate({
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

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <ChatSidebar
        activeThreadId={activeThreadId}
        onCreateThread={() => createChatSessionMutation.mutate()}
        onDeleteThread={async (threadId) => {
          const thread = threads.find((item) => item.id === threadId)
          if (thread?.sessionId) {
            await deleteChatSessionMutation.mutateAsync(thread.sessionId)
          } else {
            deleteThread(threadId)
          }
          if (useChatStore.getState().threads.length === 0) {
            createChatSessionMutation.mutate()
          }
        }}
        onRenameThread={async (threadId, title) => {
          const thread = threads.find((item) => item.id === threadId)
          renameThread(threadId, title)
          if (thread?.sessionId) {
            await updateChatSessionMutation.mutateAsync({
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
          activeView={activeView}
          buckets={buckets}
          grafanaUrl={GRAFANA_URL}
          models={approachModels}
          onChangeApproach={handleChangeApproach}
          onChangeChatMode={handleChangeChatMode}
          onChangeBucket={handleChangeBucket}
          onChangeModel={handleChangeModel}
          onChangeView={(view) => {
            if (view === 'chat') {
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

        {activeView === 'chat' ? (
          <ChatWorkspace
            activeBucket={activeBucket}
            approach={selectedApproach}
            chatMode={selectedChatMode}
            composerValue={composerValue}
            isSending={isSendingMessage}
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
            currentUserId={currentUser!.id}
            documents={documents}
            onCancelStagedDocument={(uploadId) =>
              cancelStagedDocumentMutation.mutateAsync(uploadId)
            }
            onCommitChanges={async (bucketId, changes) => {
              await commitBucketDocumentsMutation.mutateAsync({ bucketId, ...changes })
            }}
            onCreateBucket={() => createBucketMutation.mutate()}
            onDeleteBucket={(bucketId) => deleteBucketMutation.mutateAsync(bucketId)}
            onDownloadDocuments={async (bucketId, documentIds, fallbackFileName) => {
              await downloadBucketDocuments(bucketId, documentIds, fallbackFileName)
            }}
            onDeleteDocument={async (documentId) => {
              try {
                await deleteDocumentMutation.mutateAsync(documentId)
              } catch (error) {
                if (error instanceof DocumentDeleteConflictError) {
                  const bucketNames = error.conflict.buckets.map((bucket) => bucket.name).join(', ')
                  throw new Error(
                    `Этот файл ещё используется в bucket: ${bucketNames}. Сначала уберите его из этих bucket.`,
                    { cause: error },
                  )
                }
                throw error
              }
            }}
            onInspectBucket={setInspectedBucketId}
            onRetryIndexing={async (documentId, bucketId) => {
              await retryDocumentIndexingMutation.mutateAsync({ documentId, bucketId })
            }}
            onSelectBucket={handleSelectBucketFromCard}
            onStageDocument={(file) => stageDocumentMutation.mutateAsync(file)}
            onUpdateBucket={async (bucketId, payload) => {
              await updateBucketMutation.mutateAsync({ bucketId, ...payload })
            }}
          />
        )}
      </section>
    </div>
  )
}

function asksSelectedBucketDocuments(message: string): boolean {
  const normalized = message.toLowerCase()
  return (
    normalized.includes('bucket') ||
    normalized.includes('бакет') ||
    normalized.includes('в выбранн') ||
    normalized.includes('в текущ')
  )
}

function asksAllAvailableDocuments(message: string): boolean {
  const normalized = message.toLowerCase()
  return (
    normalized.includes('всем доступ') ||
    normalized.includes('все доступ') ||
    normalized.includes('всех доступ') ||
    normalized.includes('по всем документ') ||
    normalized.includes('all available')
  )
}

function normalizeDocumentName(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '')
    .trim()
}

function documentNameVariants(fileName: string, title: string): string[] {
  const stem = fileName.replace(/\.[^.]+$/, '')
  return Array.from(new Set([
    normalizeDocumentName(fileName),
    normalizeDocumentName(stem),
    normalizeDocumentName(title),
  ].filter(Boolean)))
}
