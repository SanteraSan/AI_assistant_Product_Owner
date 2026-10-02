import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TopBar } from './TopBar'

const props = {
  activeBucketId: '',
  activeView: 'chat' as const,
  buckets: [],
  models: [{ id: 'qwen', label: 'qwen', description: 'local', provider: 'ollama' as const }],
  onChangeApproach: vi.fn(),
  onChangeChatMode: vi.fn(),
  onChangeBucket: vi.fn(),
  onChangeModel: vi.fn(),
  onChangeView: vi.fn(),
  onLoginClick: vi.fn(),
  selectedApproach: 'hybrid' as const,
  selectedChatMode: 'rag' as const,
  selectedModelId: 'qwen',
}

describe('TopBar', () => {
  it('disables the knowledge base until the user signs in', () => {
    render(<TopBar {...props} user={null} />)
    expect(screen.getByRole('button', { name: 'База знаний' })).toBeDisabled()
  })
})
