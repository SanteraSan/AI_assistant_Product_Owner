import type { User } from '../../entities/user/model'
import { Button, Modal } from '../../shared/ui'

type MockLoginModalProps = {
  isOpen: boolean
  user: User
  onClose: () => void
  onLogin: () => void
}

export function MockLoginModal({ isOpen, onClose, onLogin, user }: MockLoginModalProps) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Mock login">
      <div className="rounded-2xl bg-slate-50 p-4">
        <p className="text-sm font-medium text-slate-950">{user.displayName}</p>
        <p className="mt-1 text-sm text-slate-500">{user.email}</p>
        <p className="mt-3 text-xs text-slate-500">
          Сейчас это mock auth. На этапе Keycloak/BFF этот экран будет заменён redirect flow.
        </p>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={onClose} variant="secondary">
          Отмена
        </Button>
        <Button
          onClick={() => {
            onLogin()
            onClose()
          }}
          variant="primary"
        >
          Войти как demo user
        </Button>
      </div>
    </Modal>
  )
}
