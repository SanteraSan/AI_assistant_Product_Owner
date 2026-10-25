import { create } from 'zustand'

export const PROVIDER_API_KEY_STORAGE_KEY = 'taskflow.providerApiKey'

type ProviderKeyStore = {
  providerApiKey: string
  setProviderApiKey: (value: string) => void
}

function readStoredProviderApiKey(): string {
  return localStorage.getItem(PROVIDER_API_KEY_STORAGE_KEY) ?? ''
}

export const useProviderKeyStore = create<ProviderKeyStore>((set) => ({
  providerApiKey: readStoredProviderApiKey(),
  setProviderApiKey: (value: string) => {
    if (value.trim() === '') {
      localStorage.removeItem(PROVIDER_API_KEY_STORAGE_KEY)
    } else {
      localStorage.setItem(PROVIDER_API_KEY_STORAGE_KEY, value)
    }
    set({ providerApiKey: value })
  },
}))
