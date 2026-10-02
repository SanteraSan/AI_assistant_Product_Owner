import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { StagedDocumentItem } from '../../entities/document/model'
import { Button } from '../../shared/ui'
import { StagedDocumentRow } from './StagedDocumentRow'

const staged: StagedDocumentItem = {
  id: 'upload-1',
  fileName: 'notes.txt',
  sourceType: 'txt',
  status: 'staged',
  sizeBytes: 10,
  uploadedAt: '2026-10-01',
}

describe('StagedDocumentRow', () => {
  it('calls the cancel action', async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    render(
      <StagedDocumentRow
        action={<Button onClick={onCancel}>Убрать</Button>}
        document={staged}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Убрать' }))
    expect(onCancel).toHaveBeenCalledOnce()
  })
})
