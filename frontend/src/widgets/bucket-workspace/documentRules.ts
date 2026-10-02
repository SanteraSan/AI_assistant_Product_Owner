import type { DocumentItem } from '../../entities/document/model'

export function canDeleteAvailableDocument(document: DocumentItem, currentUserId: string): boolean {
  return document.ownerUserId === currentUserId && document.visibility === 'private'
}

export function statusToneForDocument(status: DocumentItem['status']) {
  if (status === 'indexed') {
    return 'success' as const
  }
  if (status === 'error' || status === 'index_failed') {
    return 'danger' as const
  }
  return 'warning' as const
}
