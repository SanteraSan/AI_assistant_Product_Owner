import { create } from 'zustand'
import { localModels } from '../model/model'
import type { ModelApproach } from '../model/model'
import type { WorkspaceView } from './model'

type WorkspaceStore = {
  activeBucketId: string
  activeView: WorkspaceView
  selectedApproach: ModelApproach
  selectedModelId: string
  openBuckets: () => void
  openChat: () => void
  selectApproach: (approach: ModelApproach) => void
  selectBucket: (bucketId: string) => void
  selectModel: (modelId: string) => void
  selectBucketAndOpenChat: (bucketId: string) => void
}

export const useWorkspaceStore = create<WorkspaceStore>((set) => ({
  activeBucketId: '',
  activeView: 'chat',
  selectedApproach: 'hybrid',
  selectedModelId: localModels[0]?.id ?? '',

  openBuckets: () => set({ activeView: 'buckets' }),
  openChat: () => set({ activeView: 'chat' }),
  selectApproach: (selectedApproach) => set({ selectedApproach }),
  selectBucket: (activeBucketId) => set({ activeBucketId }),
  selectModel: (selectedModelId) => set({ selectedModelId }),
  selectBucketAndOpenChat: (activeBucketId) =>
    set({
      activeBucketId,
      activeView: 'chat',
    }),
}))
