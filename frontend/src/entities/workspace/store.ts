import { create } from 'zustand'
import { localModels } from '../model/model'
import type { ModelApproach } from '../model/model'
import type { ChatMode } from '../chat/model'
import type { WorkspaceView } from './model'

type WorkspaceStore = {
  activeBucketId: string
  activeView: WorkspaceView
  selectedApproach: ModelApproach
  selectedChatMode: ChatMode
  selectedModelId: string
  openBuckets: () => void
  openChat: () => void
  selectApproach: (approach: ModelApproach) => void
  selectChatMode: (mode: ChatMode) => void
  selectBucket: (bucketId: string) => void
  selectModel: (modelId: string) => void
  selectBucketAndOpenChat: (bucketId: string) => void
}

export const useWorkspaceStore = create<WorkspaceStore>((set) => ({
  activeBucketId: '',
  activeView: 'chat',
  selectedApproach: 'hybrid',
  selectedChatMode: 'rag',
  selectedModelId: localModels[0]?.id ?? '',

  openBuckets: () => set({ activeView: 'buckets' }),
  openChat: () => set({ activeView: 'chat' }),
  selectApproach: (selectedApproach) => set({ selectedApproach }),
  selectChatMode: (selectedChatMode) => set({ selectedChatMode }),
  selectBucket: (activeBucketId) => set({ activeBucketId }),
  selectModel: (selectedModelId) => set({ selectedModelId }),
  selectBucketAndOpenChat: (activeBucketId) =>
    set({
      activeBucketId,
      activeView: 'chat',
    }),
}))
