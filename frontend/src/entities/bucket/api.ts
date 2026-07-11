import { apiRequest } from '../../shared/api/httpClient'
import type { User } from '../user/model'
import type { Bucket } from './model'

type BucketDto = {
  id: string
  name: string
  description: string
  status: Bucket['status']
  document_count: number
}

export async function fetchBuckets(user: User): Promise<Bucket[]> {
  const buckets = await apiRequest<BucketDto[]>('/buckets', {
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return buckets.map((bucket) => ({
    id: bucket.id,
    name: bucket.name,
    description: bucket.description,
    documentCount: bucket.document_count,
    status: bucket.status,
  }))
}

export async function createBucket(
  user: User,
  payload: {
    name: string
    description: string
  },
): Promise<Bucket> {
  const bucket = await apiRequest<BucketDto>('/buckets', {
    body: JSON.stringify(payload),
    method: 'POST',
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return {
    id: bucket.id,
    name: bucket.name,
    description: bucket.description,
    documentCount: bucket.document_count,
    status: bucket.status,
  }
}

export async function updateBucket(
  user: User,
  bucketId: string,
  payload: {
    name?: string
    description?: string
  },
): Promise<Bucket> {
  const bucket = await apiRequest<BucketDto>(`/buckets/${bucketId}`, {
    body: JSON.stringify(payload),
    method: 'PATCH',
    tenantId: user.tenantId,
    userId: user.id,
    roles: user.roles,
  })
  return {
    id: bucket.id,
    name: bucket.name,
    description: bucket.description,
    documentCount: bucket.document_count,
    status: bucket.status,
  }
}
