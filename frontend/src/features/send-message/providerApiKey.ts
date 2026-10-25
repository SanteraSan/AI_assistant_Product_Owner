import type { ChatMode } from '../../entities/chat/model'
import type { ModelApproach } from '../../entities/model/model'

export function providerApiKeyForRagRequest(
  approach: ModelApproach,
  chatMode: ChatMode,
  storedKey: string,
): string | undefined {
  const trimmed = storedKey.trim()
  if (approach === 'external' && chatMode === 'rag' && trimmed !== '') {
    return trimmed
  }
  return undefined
}
