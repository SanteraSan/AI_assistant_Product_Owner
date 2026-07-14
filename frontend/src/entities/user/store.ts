import { create } from 'zustand'
import { buildLoginUrl, fetchAuthMe, logoutAuth, userFromAuthMe } from './api'
import type { User } from './model'

type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

type AuthStore = {
  currentUser: User | null
  csrfToken: string | null
  status: AuthStatus
  bootstrap: () => Promise<void>
  login: () => void
  logout: () => Promise<void>
}

export const useAuthStore = create<AuthStore>((set) => ({
  currentUser: null,
  csrfToken: null,
  status: 'loading',
  bootstrap: async () => {
    try {
      const me = await fetchAuthMe()
      set({
        currentUser: userFromAuthMe(me),
        csrfToken: me.csrfToken,
        status: 'authenticated',
      })
    } catch {
      set({ currentUser: null, csrfToken: null, status: 'anonymous' })
    }
  },
  login: () => {
    window.location.href = buildLoginUrl()
  },
  logout: async () => {
    try {
      await logoutAuth()
    } finally {
      set({ currentUser: null, csrfToken: null, status: 'anonymous' })
    }
  },
}))
