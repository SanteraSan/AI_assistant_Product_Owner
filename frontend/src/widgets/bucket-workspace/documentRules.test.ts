import { describe, expect, it } from 'vitest'
import type { DocumentItem } from '../../entities/document/model'
import { canDeleteAvailableDocument, statusToneForDocument } from './documentRules'

function document(overrides: Partial<DocumentItem>): DocumentItem {
  return {
    id: 'doc-1',
    title: 'file',
    fileName: 'file.pdf',
    sourceType: 'pdf',
    status: 'indexed',
    visibility: 'private',
    allowedRoles: [],
    uploadedAt: '2026-10-01',
    ownerUserId: 'user-1',
    ...overrides,
  }
}

describe('canDeleteAvailableDocument', () => {
  it('allows deleting only your own private document', () => {
    expect(canDeleteAvailableDocument(document({}), 'user-1')).toBe(true)
    expect(canDeleteAvailableDocument(document({ ownerUserId: 'user-2' }), 'user-1')).toBe(false)
    expect(canDeleteAvailableDocument(document({ visibility: 'tenant' }), 'user-1')).toBe(false)
  })
})

describe('statusToneForDocument', () => {
  it('maps indexed to success and failures to danger', () => {
    expect(statusToneForDocument('indexed')).toBe('success')
    expect(statusToneForDocument('index_failed')).toBe('danger')
    expect(statusToneForDocument('indexing')).toBe('warning')
  })
})
