export type ModelApproach = 'hybrid' | 'local_only' | 'external'

export type LocalModel = {
  id: string
  label: string
  description: string
  provider?: 'ollama' | 'gemini' | 'openrouter'
}

export type ProviderCatalog = {
  geminiKeyConfigured: boolean
  openrouterKeyConfigured: boolean
  models: LocalModel[]
}

export const localModels: LocalModel[] = [
  {
    id: 'qwen3.5:9b',
    label: 'qwen3.5:9b',
    description: 'Быстрая локальная модель для RAG и общих задач.',
    provider: 'ollama',
  },
  {
    id: 'gemma4:12b',
    label: 'gemma4:12b',
    description: 'Кандидат для более сложных ответов и comparison runs.',
    provider: 'ollama',
  },
  {
    id: 'qwen3:14b',
    label: 'qwen3:14b',
    description: 'Более крупный Qwen3 для agent/RAG comparison и reasoning.',
    provider: 'ollama',
  },
  {
    id: 'qwen2.5-coder:7b',
    label: 'qwen2.5-coder:7b',
    description: 'Coder-модель и база для Text-to-SQL LoRA.',
    provider: 'ollama',
  },
]

export const externalModels: LocalModel[] = [
  {
    id: 'gemini-3.6-flash',
    label: 'gemini-3.6-flash',
    description: 'Актуальный Gemini Flash через AI Studio (OpenAI-compatible).',
    provider: 'gemini',
  },
  {
    id: 'gemini-2.5-flash',
    label: 'gemini-2.5-flash',
    description: 'Старый Flash id; у новых ключей Google его снимает.',
    provider: 'gemini',
  },
  {
    id: 'gemini-2.0-flash',
    label: 'gemini-2.0-flash',
    description: 'Gemini 2.0 Flash через AI Studio.',
    provider: 'gemini',
  },
  {
    id: 'openai/gpt-4o-mini',
    label: 'openai/gpt-4o-mini',
    description: 'Дешёвый OpenRouter id для optional smoke.',
    provider: 'openrouter',
  },
]

export const modelApproaches: Array<{ id: ModelApproach; label: string }> = [
  { id: 'hybrid', label: 'Гибрид' },
  { id: 'local_only', label: 'Только локальные' },
  { id: 'external', label: 'External' },
]

export function isExternalApproach(approach: string | undefined): boolean {
  return approach === 'external' || approach === 'openapi'
}

export function normalizeApproach(value: string | undefined): ModelApproach {
  if (value === 'local_only') {
    return 'local_only'
  }
  if (isExternalApproach(value)) {
    return 'external'
  }
  return 'hybrid'
}

export function isModelApproach(value: string | undefined): boolean {
  return value === 'hybrid' || value === 'local_only' || value === 'external' || value === 'openapi'
}

export function modelsForApproach(
  approach: ModelApproach,
  catalog?: ProviderCatalog | null,
): LocalModel[] {
  if (approach !== 'external') {
    return localModels
  }
  const fromHealth = (catalog?.models ?? []).filter(
    (model) => model.provider === 'gemini' || model.provider === 'openrouter',
  )
  if (fromHealth.length) {
    return fromHealth
  }
  return externalModels.map((model) => {
    if (model.provider === 'gemini' && catalog && !catalog.geminiKeyConfigured) {
      return { ...model, label: `${model.id} (ключ не задан)` }
    }
    if (model.provider === 'openrouter' && catalog && !catalog.openrouterKeyConfigured) {
      return { ...model, label: `${model.id} (ключ не задан)` }
    }
    return model
  })
}
