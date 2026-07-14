import { create } from 'zustand'

type UiStore = {
  // Reserved for non-auth UI flags.
}

export const useUiStore = create<UiStore>(() => ({}))
