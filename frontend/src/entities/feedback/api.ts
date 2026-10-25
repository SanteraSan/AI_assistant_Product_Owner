import { apiRequest } from '../../shared/api/httpClient'
import type { FeedbackCounts } from './model'

type FeedbackCountsDto = {
  noise: number
  churn_signal: number
  bug: number
  feature: number
  total: number
  indexed: number
}

export async function fetchFeedbackCounts(bucketId: string): Promise<FeedbackCounts> {
  const counts = await apiRequest<FeedbackCountsDto>(`/api/buckets/${bucketId}/feedback-counts`)
  return {
    noise: counts.noise,
    churnSignal: counts.churn_signal,
    bug: counts.bug,
    feature: counts.feature,
    total: counts.total,
    indexed: counts.indexed,
  }
}
