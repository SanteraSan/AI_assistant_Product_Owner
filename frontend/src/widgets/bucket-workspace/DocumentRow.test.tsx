import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { DocumentItem } from '../../entities/document/model'
import { DocumentRow } from './DocumentRow'

const document: DocumentItem = {
  id: 'doc-1',
  title: 'file',
  fileName: 'resume.pdf',
  sourceType: 'pdf',
  status: 'indexed',
  visibility: 'private',
  allowedRoles: [],
  uploadedAt: '2026-10-01',
}

describe('DocumentRow', () => {
  it('shows the document status', () => {
    render(<DocumentRow document={document} />)
    expect(screen.getByText('indexed')).toBeInTheDocument()
    expect(screen.getByText('resume.pdf')).toBeInTheDocument()
  })
})
