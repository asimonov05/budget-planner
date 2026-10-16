import { useQuery } from '@tanstack/react-query'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api, ApiError } from './lib/api'
import type { User } from './lib/types'
import { Layout } from './components/Layout'
import { State } from './components/ui'
import { Login } from './pages/Login'
import { Register } from './pages/Register'
import { DashboardPage } from './pages/Dashboard'
import { PlanPage } from './pages/Plan'
import { ResourcePage } from './pages/Resources'
import { GoalsPage } from './pages/Goals'
import { AnalyticsPage } from './pages/Analytics'
import { ExchangePage } from './pages/Exchange'
import { SettingsPage } from './pages/Settings'
import { CalendarPage } from './pages/Calendar'
import { AccountsPage } from './pages/Accounts'
import { NotificationsPage, ReleaseNotePage } from './pages/Notifications'

async function loadCurrentUser(): Promise<User | null> {
  try {
    return await api<User>('/auth/me')
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}

function Protected() {
  const location = useLocation()
  const me = useQuery<User | null>({ queryKey: ['me'], queryFn: loadCurrentUser, retry: false })
  const access = useQuery<{ apps: Array<{ id: string; available: boolean }> }>({
    queryKey: ['superapp-apps', me.data?.id],
    queryFn: () => api('/superapp/apps'),
    enabled: Boolean(me.data),
    retry: false,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  })
  if (me.isLoading) return <div className="fullscreen-state"><State kind="loading" title="Открываем бюджет" /></div>
  if (me.isError) return <div className="fullscreen-state"><State kind="error" title="Сервер недоступен">Проверьте, что приложение запущено, и обновите страницу.</State></div>
  if (!me.data) return <Navigate to="/login" state={{ from: location }} replace />
  if (access.isLoading) return <div className="fullscreen-state"><State kind="loading" title="Проверяем доступ к бюджету" /></div>
  if (access.isError) return <div className="fullscreen-state"><State kind="error" title="Не удалось проверить доступ" action={<button className="button button--secondary" onClick={() => access.refetch()}>Повторить</button>}>Попробуйте ещё раз или <a href="/">вернитесь ко всем приложениям</a>.</State></div>
  if (!access.data?.apps.some(app => app.id === 'budget' && app.available)) return <div className="fullscreen-state"><State title="Бюджет сейчас недоступен" action={<a className="button button--primary" href="/">Все приложения</a>}>Администратор закрыл доступ к приложению. Ваши данные сохранены.</State></div>
  return <Layout />
}

export function App() {
  const me = useQuery<User | null>({ queryKey: ['me'], queryFn: loadCurrentUser, retry: false })
  return <Routes>
    <Route path="/login" element={<Login currentUser={me.data} />} />
    <Route path="/register" element={<Register currentUser={me.data} />} />
    <Route element={<Protected />}>
      <Route index element={<DashboardPage />} />
      <Route path="accounts" element={<AccountsPage />} />
      <Route path="plan" element={<PlanPage />} />
      <Route path="calendar" element={<CalendarPage />} />
      <Route path="incomes" element={<ResourcePage type="income" />} />
      <Route path="payments" element={<ResourcePage type="payment" />} />
      <Route path="transactions" element={<ResourcePage type="transaction" />} />
      <Route path="loans" element={<ResourcePage type="loan" />} />
      <Route path="goals" element={<GoalsPage />} />
      <Route path="analytics" element={<AnalyticsPage />} />
      <Route path="exchange" element={<ExchangePage />} />
      <Route path="settings" element={<SettingsPage />} />
      <Route path="notifications" element={<NotificationsPage />} />
      <Route path="release-notes/:id" element={<ReleaseNotePage />} />
    </Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
}
