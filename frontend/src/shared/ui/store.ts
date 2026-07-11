import { create } from 'zustand'

type UiStore = {
  isLoginModalOpen: boolean
  closeLoginModal: () => void
  openLoginModal: () => void
}

export const useUiStore = create<UiStore>((set) => ({
  isLoginModalOpen: false,
  closeLoginModal: () => set({ isLoginModalOpen: false }),
  openLoginModal: () => set({ isLoginModalOpen: true }),
}))
