import { apiRequest } from '../../shared/api/httpClient'
import type { Bucket } from './model'

type BucketDto = {
  id: string
  name: string
  description: string
  status: Bucket['status']
  document_count: number
}

export async function fetchBuckets(): Promise<Bucket[]> {
  const buckets = await apiRequest<BucketDto[]>('/api/buckets')
  return buckets.map((bucket) => ({
    id: bucket.id,
    name: bucket.name,
    description: bucket.description,
    documentCount: bucket.document_count,
    status: bucket.status
  }))
}

export async function createBucket(
  payload: {
    name: string
    description: string
  },
): Promise<Bucket> {
  const bucket = await apiRequest<BucketDto>('/api/buckets', {
    body: JSON.stringify(payload),
    method: 'POST'
  })
  return {
    id: bucket.id,
    name: bucket.name,
    description: bucket.description,
    documentCount: bucket.document_count,
    status: bucket.status
  }
}

export async function updateBucket(
  bucketId: string,
  payload: {
    name?: string
    description?: string
  },
): Promise<Bucket> {
  const bucket = await apiRequest<BucketDto>(`/api/buckets/${bucketId}`, {
    body: JSON.stringify(payload),
    method: 'PATCH'
  })
  return {
    id: bucket.id,
    name: bucket.name,
    description: bucket.description,
    documentCount: bucket.document_count,
    status: bucket.status
  }
}

export async function deleteBucket(bucketId: string): Promise<void> {
  await apiRequest<void>(`/api/buckets/${bucketId}`, {
    method: 'DELETE'
  })
}
