import { useState } from 'react'
import { mockBuckets } from '../../entities/bucket/model'
import { useChatStore } from '../../entities/chat/store'
import { mockDocuments } from '../../entities/document/model'
import { localModels } from '../../entities/model/model'
import type { ModelApproach } from '../../entities/model/model'
import { mockUser } from '../../entities/user/model'
import type { User } from '../../entities/user/model'
import { MockLoginModal } from '../../features/mock-login/MockLoginModal'
import { BucketWorkspace } from '../../widgets/bucket-workspace/BucketWorkspace'
import { ChatSidebar } from '../../widgets/chat-sidebar/ChatSidebar'
import { ChatWorkspace } from '../../widgets/chat-workspace/ChatWorkspace'
import { TopBar } from '../../widgets/top-bar/TopBar'

export function ChatPage() {
  const [activeBucketId, setActiveBucketId] = useState(mockBuckets[0]?.id ?? '')
  const [activeView, setActiveView] = useState<'chat' | 'buckets'>('chat')
  const [isLoginOpen, setIsLoginOpen] = useState(false)
  const [selectedApproach, setSelectedApproach] = useState<ModelApproach>('hybrid')
  const [selectedModelId, setSelectedModelId] = useState(localModels[0]?.id ?? '')
  const [user, setUser] = useState<User | null>(null)
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

  const activeBucket = mockBuckets.find((bucket) => bucket.id === activeBucketId)
  const selectedModel = localModels.find((model) => model.id === selectedModelId)
  const messages = messagesByThreadId[activeThreadId] ?? []

  function handleSendMessage() {
    sendMessage(composerValue, {
      bucketId: activeBucket?.id ?? activeBucketId,
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
          activeBucketId={activeBucketId}
          activeView={activeView}
          buckets={mockBuckets}
          models={localModels}
          onChangeApproach={setSelectedApproach}
          onChangeBucket={setActiveBucketId}
          onChangeModel={setSelectedModelId}
          onChangeView={setActiveView}
          onLoginClick={() => setIsLoginOpen(true)}
          selectedApproach={selectedApproach}
          selectedModelId={selectedModelId}
          user={user}
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
            buckets={mockBuckets}
            documents={mockDocuments}
            onCreateBucket={() => undefined}
            onSelectBucket={(bucketId) => {
              setActiveBucketId(bucketId)
              setActiveView('chat')
            }}
          />
        )}
      </section>

      <MockLoginModal
        isOpen={isLoginOpen}
        onClose={() => setIsLoginOpen(false)}
        onLogin={setUser}
        user={mockUser}
      />
    </div>
  )
}
