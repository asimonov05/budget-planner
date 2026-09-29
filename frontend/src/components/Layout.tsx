import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BarChart3, Bug, CalendarDays, ChevronLeft, ChevronRight, CreditCard, FileUp, Flag, LayoutDashboard,
  LogOut, Menu, PanelLeftClose, PiggyBank, ReceiptText, Settings, TableProperties, WalletCards, X,
} from 'lucide-react'
import { api } from '../lib/api'
import type { User } from '../lib/types'

const navigation = [
  { to: '/', label: 'Обзор', icon: LayoutDashboard, end: true },
  { to: '/plan', label: 'План', icon: TableProperties },
  { to: '/calendar', label: 'Календарь', icon: CalendarDays },
  { to: '/incomes', label: 'Доходы', icon: PiggyBank },
  { to: '/payments', label: 'Платежи', icon: ReceiptText },
  { to: '/transactions', label: 'Операции', icon: WalletCards },
  { to: '/loans', label: 'Кредиты', icon: CreditCard },
  { to: '/goals', label: 'Цели', icon: Flag },
  { to: '/analytics', label: 'Аналитика', icon: BarChart3 },
  { to: '/exchange', label: 'Импорт и экспорт', icon: FileUp },
  { to: '/settings', label: 'Настройки', icon: Settings },
]

export function Layout() {
  const [compact, setCompact] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const navigate = useNavigate(); const queryClient = useQueryClient()
  const me = useQuery<User>({ queryKey: ['me'], queryFn: () => api<User>('/auth/me') })
  const logout = useMutation({ mutationFn: () => api('/auth/logout', { method: 'POST' }), onSuccess: () => { queryClient.clear(); navigate('/login') } })
  return <div className={`app-shell ${compact ? 'is-compact' : ''}`}>
    <aside className={`sidebar ${mobileOpen ? 'is-open' : ''}`}>
      <div className="brand"><div className="brand-mark">К</div><div className="brand-copy"><strong>Контур</strong><span>Личный бюджет</span></div><button className="mobile-close icon-button" onClick={() => setMobileOpen(false)}><X /></button></div>
      <nav aria-label="Основное меню">{navigation.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setMobileOpen(false)}><Icon/><span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-bottom">
        <button className="sidebar-action" onClick={() => setCompact((v) => !v)}>{compact ? <ChevronRight /> : <PanelLeftClose />}<span>Свернуть</span></button>
        {me.data?.debug_admin_enabled && <a className="sidebar-action" href="/admin/"><Bug/><span>Админка</span></a>}
        <button className="sidebar-action" onClick={() => logout.mutate()} disabled={logout.isPending}><LogOut/><span>Выйти</span></button>
      </div>
    </aside>
    {mobileOpen && <button className="sidebar-scrim" onClick={() => setMobileOpen(false)} aria-label="Закрыть меню" />}
    <main><div className="mobile-bar"><button className="icon-button" onClick={() => setMobileOpen(true)}><Menu /></button><span>Контур</span></div><Outlet /></main>
  </div>
}
