export type ModelApproach = 'hybrid' | 'local_only' | 'openapi'

export type LocalModel = {
  id: string
  label: string
  description: string
}

export const localModels: LocalModel[] = [
  {
    id: 'qwen3.5:9b',
    label: 'qwen3.5:9b',
    description: 'Быстрая локальная модель для RAG и общих задач.',
  },
  {
    id: 'gemma4:12b',
    label: 'gemma4:12b',
    description: 'Кандидат для более сложных ответов и comparison runs.',
  },
  {
    id: 'qwen2.5-coder:7b',
    label: 'qwen2.5-coder:7b',
    description: 'Coder-модель и база для Text-to-SQL LoRA.',
  },
]

export const modelApproaches: Array<{ id: ModelApproach; label: string }> = [
  { id: 'hybrid', label: 'Гибрид' },
  { id: 'local_only', label: 'Только локальные' },
  { id: 'openapi', label: 'OpenAPI' },
]
