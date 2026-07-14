import type { Bucket } from '../../entities/bucket/model'
import type { ChatMode } from '../../entities/chat/model'
import type { LocalModel, ModelApproach } from '../../entities/model/model'
import { modelApproaches } from '../../entities/model/model'
import type { User } from '../../entities/user/model'
import { Button, Select } from '../../shared/ui'

const chatModeOptions = [
  { id: 'rag' as const, label: 'RAG' },
  { id: 'agent' as const, label: 'Agent' },
]

type TopBarProps = {
  buckets: Bucket[]
  activeBucketId: string
  activeView: 'chat' | 'buckets'
  models: LocalModel[]
  selectedApproach: ModelApproach
  selectedChatMode: ChatMode
  selectedModelId: string
  user: User | null
  onChangeApproach: (approach: ModelApproach) => void
  onChangeChatMode: (mode: ChatMode) => void
  onChangeBucket: (bucketId: string) => void
  onChangeModel: (modelId: string) => void
  onChangeView: (view: 'chat' | 'buckets') => void
  onLoginClick: () => void
  onLogoutClick?: () => void
}

export function TopBar({
  activeBucketId,
  activeView,
  buckets,
  models,
  onChangeApproach,
  onChangeChatMode,
  onChangeBucket,
  onChangeModel,
  onChangeView,
  onLoginClick,
  onLogoutClick,
  selectedApproach,
  selectedChatMode,
  selectedModelId,
  user,
}: TopBarProps) {
  return (
    <header className="flex min-h-20 items-center justify-between gap-4 border-b border-slate-200 bg-white px-6">
      <div className="flex items-center gap-3">
        <Button
          onClick={() => onChangeView('chat')}
          variant={activeView === 'chat' ? 'primary' : 'secondary'}
        >
          Чат
        </Button>
        <Button
          onClick={() => onChangeView('buckets')}
          variant={activeView === 'buckets' ? 'primary' : 'secondary'}
        >
          База знаний
        </Button>
      </div>

      <div className="flex flex-1 items-center justify-end gap-3">
        <Select
          label="Режим"
          onChange={(event) => onChangeChatMode(event.target.value as ChatMode)}
          options={chatModeOptions.map((mode) => ({
            label: mode.label,
            value: mode.id,
          }))}
          value={selectedChatMode}
        />
        <Select
          label="Модель"
          onChange={(event) => onChangeModel(event.target.value)}
          options={models.map((model) => ({ label: model.label, value: model.id }))}
          value={selectedModelId}
        />
        <Select
          label="Подход"
          onChange={(event) => onChangeApproach(event.target.value as ModelApproach)}
          options={modelApproaches.map((approach) => ({
            label: approach.label,
            value: approach.id,
          }))}
          value={selectedApproach}
        />
        <Select
          label="Контекст"
          onChange={(event) => onChangeBucket(event.target.value)}
          options={[
            { label: 'Без bucket', value: '' },
            ...buckets.map((bucket) => ({ label: bucket.name, value: bucket.id })),
          ]}
          value={activeBucketId}
        />
        <Button onClick={user ? onLogoutClick ?? onLoginClick : onLoginClick} variant="ghost">
          {user ? 'Выйти' : 'Войти'}
        </Button>
      </div>
    </header>
  )
}
