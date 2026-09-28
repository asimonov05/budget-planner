import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import { initializeTheme, ThemeProvider } from './lib/theme'
import './fonts.css'
import './styles.css'
import './themes.css'

initializeTheme()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false },
    mutations: { retry: 0 },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider><BrowserRouter><App /></BrowserRouter></ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
