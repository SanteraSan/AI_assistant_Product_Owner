import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DeleteDocumentDialog } from './DeleteDocumentDialog'

describe('DeleteDocumentDialog', () => {
  it('confirms deletion through the callback', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(
      <DeleteDocumentDialog
        error={null}
        fileName="resume.pdf"
        isDeleting={false}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Удалить' }))
    expect(onConfirm).toHaveBeenCalledOnce()
  })
})
