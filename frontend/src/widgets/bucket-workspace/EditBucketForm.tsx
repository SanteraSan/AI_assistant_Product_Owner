import { DialogActions, Input, Notice, Textarea } from '../../shared/ui'

type EditBucketFormProps = {
  description: string
  error: string | null
  name: string
  onCancel: () => void
  onChangeDescription: (value: string) => void
  onChangeName: (value: string) => void
  onSave: () => void
  pending: boolean
}

export function EditBucketForm({
  description,
  error,
  name,
  onCancel,
  onChangeDescription,
  onChangeName,
  onSave,
  pending,
}: EditBucketFormProps) {
  return (
    <div className="space-y-4">
      <label className="block space-y-2 text-sm text-slate-700">
        <span>Название</span>
        <Input onChange={(event) => onChangeName(event.target.value)} value={name} />
      </label>
      <label className="block space-y-2 text-sm text-slate-700">
        <span>Описание</span>
        <Textarea
          onChange={(event) => onChangeDescription(event.target.value)}
          value={description}
          variant="field"
        />
      </label>
      {error ? <Notice compact>{error}</Notice> : null}
      <DialogActions
        confirmLabel="Сохранить"
        onCancel={onCancel}
        onConfirm={onSave}
        pending={pending}
        pendingLabel="Сохраняем..."
      />
    </div>
  )
}
