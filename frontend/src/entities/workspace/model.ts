import type { ModelApproach } from '../model/model'

export type WorkspaceView = 'chat' | 'buckets'

export type WorkspaceState = {
  activeBucketId: string
  activeView: WorkspaceView
  selectedApproach: ModelApproach
  selectedModelId: string
}
