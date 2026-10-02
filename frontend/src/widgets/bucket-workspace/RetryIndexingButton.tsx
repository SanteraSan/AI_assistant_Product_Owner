import { RotateCcw } from 'lucide-react'
import { Button } from '../../shared/ui'

type RetryIndexingButtonProps = {
  disabled: boolean
  onClick: () => void
  pending: boolean
}

export function RetryIndexingButton({ disabled, onClick, pending }: RetryIndexingButtonProps) {
  return (
    <Button disabled={disabled} onClick={onClick} variant="ghost">
      <RotateCcw size={14} />
      {pending ? 'Повтор...' : 'Повторить'}
    </Button>
  )
}
