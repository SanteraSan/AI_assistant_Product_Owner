import { create } from 'zustand'
import type { User } from './model'
import { mockUser } from './model'

type AuthStore = {
  currentUser: User | null
  loginAsMockUser: () => void
  logout: () => void
}

export const useAuthStore = create<AuthStore>((set) => ({
  currentUser: null,
  loginAsMockUser: () => set({ currentUser: mockUser }),
  logout: () => set({ currentUser: null }),
}))
