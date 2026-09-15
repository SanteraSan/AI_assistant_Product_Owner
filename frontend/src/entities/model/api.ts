import { apiRequest } from '../../shared/api/httpClient'
import type { LocalModel, ProviderCatalog } from './model'

type HealthDto = {
  gemini_key_configured?: boolean
  openrouter_key_configured?: boolean
  models?: Array<{
    id: string
    provider: string
    label: string
  }>
}

export async function fetchProviderCatalog(): Promise<ProviderCatalog> {
  const health = await apiRequest<HealthDto>('/api/health')
  const models: LocalModel[] = (health.models ?? []).map((entry) => ({
    id: entry.id,
    label: entry.label,
    description: entry.provider,
    provider:
      entry.provider === 'gemini' || entry.provider === 'openrouter' || entry.provider === 'ollama'
        ? entry.provider
        : undefined,
  }))
  return {
    geminiKeyConfigured: Boolean(health.gemini_key_configured),
    openrouterKeyConfigured: Boolean(health.openrouter_key_configured),
    models,
  }
}
