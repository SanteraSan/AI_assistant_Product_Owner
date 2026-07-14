import type { ReactNode } from 'react'
import { useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { useAuthStore } from '../../entities/user/store'

const queryClient = new QueryClient()

type AppProvidersProps = {
  children: ReactNode
}

function AuthBootstrap({ children }: { children: ReactNode }) {
  const bootstrap = useAuthStore((state) => state.bootstrap)
  const status = useAuthStore((state) => state.status)

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 text-slate-600">
        Проверка сессии…
      </div>
    )
  }

  return <>{children}</>
}

export function AppProviders({ children }: AppProvidersProps) {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthBootstrap>{children}</AuthBootstrap>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
