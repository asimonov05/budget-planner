import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown, ArrowUp, BarChart3, Bell, Bug, CalendarDays, ChevronRight, CreditCard,
  FileUp, Flag, GripVertical, Landmark, LayoutDashboard, LogOut, Menu, PanelLeftClose,
  PiggyBank, ReceiptText, Settings, SlidersHorizontal, TableProperties, WalletCards, X,
  AppWindow,
} from 'lucide-react'
import { api } from '../lib/api'
import {
  defaultMenuPreferences, menuStorageKey, moveMenuItem, readMenuPreferences,
  saveMenuPreferences, type MenuPreferences,
} from '../lib/menuPreferences'
import type { User } from '../lib/types'
import { Button, Modal } from './ui'
import { ReleasePreviewPopup, type ReleasePreview } from './ReleasePreviewPopup'
import './menu-editor.css'

const navigation = [
  { to: '/', label: 'Обзор', icon: LayoutDashboard, end: true },
  { to: '/accounts', label: 'Счета', icon: Landmark },
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
  { to: '/notifications', label: 'Уведомления', icon: Bell },
]

const navigationPaths = navigation.map((item) => item.to)
const navigationByPath = new Map(navigation.map((item) => [item.to, item] as const))
const releasePreviewSeenKey = (owner: string, id: number) => `budget-planner-release-preview-seen:${owner}:${id}`

function releasePreviewWasSeen(owner: string | null, id: number) {
  if (!owner) return false
  try {
    return window.sessionStorage.getItem(releasePreviewSeenKey(owner, id)) === '1'
  } catch {
    return false
  }
}

function MenuEditor({
  preferences, storageError, onMove, onToggle, onReset, onClose,
}: {
  preferences: MenuPreferences
  storageError: boolean
  onMove: (source: string, target: string) => void
  onToggle: (path: string) => void
  onReset: () => void
  onClose: () => void
}) {
  const [dragging, setDragging] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const previousPositions = useRef(new Map<string, number>())
  const animations = useRef<Animation[]>([])

  const capturePositions = () => {
    previousPositions.current = new Map(
      [...(listRef.current?.querySelectorAll<HTMLElement>('[data-menu-path]') ?? [])]
        .map((row) => [row.dataset.menuPath!, row.getBoundingClientRect().top]),
    )
  }
  const moveAnimated = (source: string, target: string) => {
    if (source === target) return
    capturePositions()
    onMove(source, target)
  }

  useLayoutEffect(() => {
    const previous = previousPositions.current
    if (!previous.size) return
    previousPositions.current = new Map()
    animations.current.forEach((animation) => animation.cancel())
    animations.current = []
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    listRef.current?.querySelectorAll<HTMLElement>('[data-menu-path]').forEach((row) => {
      const before = previous.get(row.dataset.menuPath!)
      if (before === undefined || typeof row.animate !== 'function') return
      const distance = before - row.getBoundingClientRect().top
      if (Math.abs(distance) < 1) return
      animations.current.push(row.animate(
        [{ transform: `translateY(${distance}px)` }, { transform: 'translateY(0)' }],
        { duration: 230, easing: 'cubic-bezier(.22, 1, .36, 1)' },
      ))
    })
  }, [preferences.order])

  useEffect(() => () => animations.current.forEach((animation) => animation.cancel()), [])

  return <Modal title="Настроить меню" onClose={onClose}>
    <p className="menu-editor-intro">Перетащите пункт или используйте стрелки. Скрытые страницы останутся доступны по прямой ссылке. Выбор сохраняется в этом браузере.</p>
    {storageError && <div className="form-alert" role="alert">Не удалось сохранить настройку в браузере. Она действует до обновления страницы.</div>}
    <div className="menu-editor-list" ref={listRef}>
      {preferences.order.map((path, index) => {
        const item = navigationByPath.get(path)
        if (!item) return null
        const Icon = item.icon
        const visible = !preferences.hidden.includes(path)
        const dropDirection = dragging && dropTarget === path && dragging !== path
          ? preferences.order.indexOf(dragging) < index ? 'is-drop-after' : 'is-drop-before'
          : ''
        return <div
          key={path}
          data-menu-path={path}
          draggable
          className={`menu-editor-row ${visible ? '' : 'is-hidden'} ${dragging === path ? 'is-dragged' : ''} ${dropDirection}`}
          onDragStart={(event) => {
            if (event.target instanceof Element && event.target.closest('.menu-editor-toggle, .menu-editor-move')) {
              event.preventDefault()
              return
            }
            event.dataTransfer.effectAllowed = 'move'
            event.dataTransfer.setData('text/plain', path)
            const rect = event.currentTarget.getBoundingClientRect()
            event.dataTransfer.setDragImage?.(
              event.currentTarget,
              Math.max(0, event.clientX - rect.left),
              Math.max(0, event.clientY - rect.top),
            )
            setDragging(path)
            setDropTarget(null)
          }}
          onDragOver={(event) => {
            if (!dragging) return
            event.preventDefault()
            event.dataTransfer.dropEffect = 'move'
            if (dropTarget !== path) setDropTarget(path)
          }}
          onDrop={(event) => {
            if (!dragging) return
            event.preventDefault()
            moveAnimated(dragging, path)
            setDragging(null)
            setDropTarget(null)
          }}
          onDragEnd={() => { setDragging(null); setDropTarget(null) }}
        >
          <button
            type="button"
            className="menu-editor-drag"
            draggable
            aria-label={`Перетащить ${item.label}`}
            title="Перетащить"
          ><GripVertical aria-hidden="true"/></button>
          <span className="menu-editor-label"><Icon aria-hidden="true"/>{item.label}</span>
          <label className="menu-editor-toggle">
            <input type="checkbox" checked={visible} onChange={() => onToggle(path)} aria-label={`Показывать ${item.label}`}/>
            <span>Показывать</span>
          </label>
          <span className="menu-editor-move">
            <button type="button" className="icon-button" disabled={index === 0} aria-label={`Поднять ${item.label}`} onClick={() => moveAnimated(path, preferences.order[index - 1])}><ArrowUp aria-hidden="true"/></button>
            <button type="button" className="icon-button" disabled={index === preferences.order.length - 1} aria-label={`Опустить ${item.label}`} onClick={() => moveAnimated(path, preferences.order[index + 1])}><ArrowDown aria-hidden="true"/></button>
          </span>
        </div>
      })}
    </div>
    <div className="menu-editor-actions">
      <Button variant="secondary" onClick={() => { capturePositions(); onReset() }}>Сбросить меню</Button>
      <Button onClick={onClose}>Готово</Button>
    </div>
  </Modal>
}

export function Layout() {
  const [compact, setCompact] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [storageError, setStorageError] = useState(false)
  const [dismissedPreviewId, setDismissedPreviewId] = useState<number | null>(null)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const me = useQuery<User>({ queryKey: ['me'], queryFn: () => api<User>('/auth/me') })
  const menuOwner = me.data?.id != null
    ? `id-${me.data.id}`
    : me.data?.username ? `name-${me.data.username}` : null
  const [preferences, setPreferences] = useState<MenuPreferences>(() => defaultMenuPreferences(navigationPaths))

  useEffect(() => {
    setPreferences(readMenuPreferences(menuOwner, navigationPaths))
    setStorageError(false)
    setDismissedPreviewId(null)
    if (!menuOwner) return undefined
    const onStorage = (event: StorageEvent) => {
      if (event.key === menuStorageKey(menuOwner)) {
        setPreferences(readMenuPreferences(menuOwner, navigationPaths))
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [menuOwner])

  const unread = useQuery<{ count: number }>({
    queryKey: ['notifications', 'count'],
    queryFn: () => api('/notifications/unread-count'),
    enabled: Boolean(me.data) && !preferences.hidden.includes('/notifications'),
    refetchInterval: 60_000,
  })
  const releasePreview = useQuery<ReleasePreview | null>({
    queryKey: ['notifications', 'release-preview', menuOwner],
    queryFn: () => api('/notifications/release-preview'),
    enabled: Boolean(me.data),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
  const logout = useMutation({
    mutationFn: () => api('/auth/logout', { method: 'POST' }),
    onSuccess: () => { queryClient.clear(); navigate('/login') },
  })

  const updatePreferences = (next: MenuPreferences) => {
    setPreferences(next)
    setStorageError(!saveMenuPreferences(menuOwner, next))
  }
  const move = (source: string, target: string) => {
    updatePreferences({ ...preferences, order: moveMenuItem(preferences.order, source, target) })
  }
  const toggle = (path: string) => {
    updatePreferences({
      ...preferences,
      hidden: preferences.hidden.includes(path)
        ? preferences.hidden.filter((item) => item !== path)
        : [...preferences.hidden, path],
    })
  }
  const orderedNavigation = preferences.order
    .map((path) => navigationByPath.get(path))
    .filter((item): item is (typeof navigation)[number] => Boolean(item))
    .filter((item) => !preferences.hidden.includes(item.to))
  const notificationCount = unread.data?.count ?? 0
  const preview = releasePreview.data
  const showReleasePreview = preview && !preview.read_at
    && dismissedPreviewId !== preview.id
    && !releasePreviewWasSeen(menuOwner, preview.id)
  const dismissReleasePreview = () => {
    if (!preview) return
    setDismissedPreviewId(preview.id)
    if (!menuOwner) return
    try {
      window.sessionStorage.setItem(releasePreviewSeenKey(menuOwner, preview.id), '1')
    } catch {
      // Dismissal still works until this layout is unmounted.
    }
  }

  return <div className={`app-shell ${compact ? 'is-compact' : ''}`}>
    <aside className={`sidebar ${mobileOpen ? 'is-open' : ''}`}>
      <div className="brand">
        <div className="brand-mark">К</div>
        <div className="brand-copy"><strong>Контур</strong><span>Личный бюджет</span></div>
        <button className="mobile-close icon-button" aria-label="Закрыть меню" onClick={() => setMobileOpen(false)}><X/></button>
      </div>
      <nav aria-label="Основное меню">
        {orderedNavigation.map(({ to, label, icon: Icon, end }) => <NavLink
          key={to}
          to={to}
          end={end}
          title={label}
          aria-label={to === '/notifications' && notificationCount ? `${label}, непрочитанных: ${notificationCount}` : label}
          onClick={() => setMobileOpen(false)}
        >
          <Icon aria-hidden="true"/>
          <span>{label}</span>
          {to === '/notifications' && notificationCount > 0 && <span className="notification-nav-count" aria-hidden="true">{notificationCount > 99 ? '99+' : notificationCount}</span>}
        </NavLink>)}
      </nav>
      <div className="sidebar-bottom">
        <a className="sidebar-action" href="/" aria-label="Все приложения"><AppWindow aria-hidden="true"/><span>Все приложения</span></a>
        <button
          className="sidebar-action"
          aria-label="Настроить меню"
          title="Настроить меню"
          onClick={() => { setMobileOpen(false); setMenuOpen(true) }}
          disabled={!menuOwner}
        ><SlidersHorizontal aria-hidden="true"/><span>Настроить меню</span></button>
        <button className="sidebar-action" aria-label={compact ? 'Развернуть меню' : 'Свернуть меню'} onClick={() => setCompact((value) => !value)}>{compact ? <ChevronRight aria-hidden="true"/> : <PanelLeftClose aria-hidden="true"/>}<span>{compact ? 'Развернуть' : 'Свернуть'}</span></button>
        {me.data?.debug_admin_enabled && <a className="sidebar-action" href="/admin/" aria-label="Админка"><Bug aria-hidden="true"/><span>Админка</span></a>}
        <button className="sidebar-action" aria-label="Выйти" onClick={() => logout.mutate()} disabled={logout.isPending}><LogOut aria-hidden="true"/><span>Выйти</span></button>
      </div>
    </aside>
    {mobileOpen && <button className="sidebar-scrim" onClick={() => setMobileOpen(false)} aria-label="Закрыть меню"/>}
    <main>
      <div className="mobile-bar"><button className="icon-button" aria-label="Открыть меню" onClick={() => setMobileOpen(true)}><Menu/></button><span>Контур</span></div>
      <Outlet/>
    </main>
    {menuOpen && <MenuEditor
      preferences={preferences}
      storageError={storageError}
      onMove={move}
      onToggle={toggle}
      onReset={() => updatePreferences(defaultMenuPreferences(navigationPaths))}
      onClose={() => setMenuOpen(false)}
    />}
    {showReleasePreview && <ReleasePreviewPopup
      preview={preview}
      onDismiss={dismissReleasePreview}
      onOpen={() => { dismissReleasePreview(); navigate('/notifications') }}
    />}
  </div>
}
