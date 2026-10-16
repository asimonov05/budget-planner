import type { ReactNode } from 'react'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Bell, Check, CheckCheck, FileText, Sparkles } from 'lucide-react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import type { User } from '../lib/types'
import { Button, Card, PageHeader, State } from '../components/ui'
import './notifications.css'

interface Notification {
  id: number
  kind: 'message' | 'release'
  title: string
  body: string
  release_note_id: number | null
  created_at: string
  read_at: string | null
}

interface Inbox { items: Notification[]; total: number; unread: number }
interface ReleaseNote {
  id: number
  release_version: string
  title: string
  summary: string
  body: string
  status: 'draft' | 'published'
  created_at: string
  updated_at: string
  published_at: string | null
}
type Tab = 'inbox' | 'releases'

function timeLabel(value: string) {
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(value))
}

function invalidateInbox(client: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    client.invalidateQueries({ queryKey: ['notifications', 'list'] }),
    client.invalidateQueries({ queryKey: ['notifications', 'count'] }),
    client.invalidateQueries({ queryKey: ['notifications', 'release-preview'] }),
  ])
}

function NotificationIcon({ kind }: { kind: Notification['kind'] }) {
  return <span className={`notification-icon notification-icon--${kind}`} aria-hidden="true">
    {kind === 'release' ? <Sparkles /> : <Bell />}
  </span>
}

function ReleaseArticle({ body }: { body: string }) {
  const blocks: ReactNode[] = []
  let paragraph: string[] = []
  let list: string[] = []
  const flushParagraph = () => {
    if (paragraph.length) blocks.push(<p key={`p-${blocks.length}`}>{paragraph.join(' ')}</p>)
    paragraph = []
  }
  const flushList = () => {
    if (list.length) blocks.push(<ul key={`l-${blocks.length}`}>{list.map((item, index) => <li key={index}>{item}</li>)}</ul>)
    list = []
  }
  for (const rawLine of body.replace(/\r\n?/g, '\n').split('\n')) {
    const line = rawLine.trim()
    if (!line) { flushParagraph(); flushList(); continue }
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      flushParagraph(); flushList()
      const title = heading[2]
      blocks.push(heading[1].length === 1 ? <h2 key={`h-${blocks.length}`}>{title}</h2> : <h3 key={`h-${blocks.length}`}>{title}</h3>)
      continue
    }
    const bullet = line.match(/^(?:[-*]|\d+\.)\s+(.+)$/)
    if (bullet) { flushParagraph(); list.push(bullet[1]); continue }
    flushList()
    paragraph.push(line)
  }
  flushParagraph(); flushList()
  return <div className="release-article">{blocks}</div>
}

export function NotificationsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const tab: Tab = requestedTab === 'releases' ? requestedTab : 'inbox'
  const setTab = (next: Tab) => setSearchParams(next === 'inbox' ? {} : { tab: next })
  const me = useQuery<User>({ queryKey: ['me'], queryFn: () => api('/auth/me') })
  return <div className="page notifications-page">
    <PageHeader eyebrow="Связь" title="Уведомления" description="Важные сообщения и новости приложения в одном месте." />
    <div className="notification-tabs" role="tablist" aria-label="Разделы уведомлений">
      <button role="tab" aria-selected={tab === 'inbox'} className={tab === 'inbox' ? 'active' : ''} onClick={() => setTab('inbox')}><Bell aria-hidden="true" /> Входящие</button>
      <button role="tab" aria-selected={tab === 'releases'} className={tab === 'releases' ? 'active' : ''} onClick={() => setTab('releases')}><FileText aria-hidden="true" /> История версий</button>
    </div>
    {tab === 'inbox' && <InboxView />}
    {tab === 'releases' && <ReleaseHistory />}
    {me.data?.is_admin && <a className="notification-detail-link" href="/admin/#publications">Управление публикациями в cap space <ArrowRight aria-hidden="true" /></a>}
  </div>
}

function InboxView() {
  const client = useQueryClient()
  const inbox = useInfiniteQuery({
    queryKey: ['notifications', 'list'],
    queryFn: ({ pageParam }) => api<Inbox>(`/notifications?limit=50&offset=${pageParam}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const loaded = pages.reduce((count, page) => count + page.items.length, 0)
      return lastPage.items.length === 50 && loaded < lastPage.total ? loaded : undefined
    },
  })
  const items = inbox.data?.pages.flatMap((page) => page.items) ?? []
  const unread = inbox.data?.pages[0]?.unread ?? 0
  const read = useMutation({
    mutationFn: (id: number) => api(`/notifications/${id}/read`, { method: 'POST' }),
    onSuccess: async () => { await invalidateInbox(client) },
  })
  const readAll = useMutation({
    mutationFn: () => api<{ updated: number }>('/notifications/read-all', { method: 'POST' }),
    onSuccess: async () => { await invalidateInbox(client) },
  })
  if (inbox.isLoading) return <State kind="loading" title="Загружаем уведомления" />
  if (inbox.isError) return <State kind="error" title="Не удалось загрузить уведомления">{inbox.error.message}</State>
  return <section aria-label="Входящие уведомления">
    <div className="notification-list-head">
      <div><strong>Входящие</strong><span>{unread ? `${unread} непрочитанных` : 'Всё прочитано'}</span></div>
      <Button variant="ghost" disabled={!unread || readAll.isPending || read.isPending} onClick={() => readAll.mutate()}><CheckCheck aria-hidden="true" /> Прочитать все</Button>
    </div>
    {!items.length ? <Card className="notification-empty"><State title="Пока нет сообщений">Здесь появятся уведомления владельца и новости релизов.</State></Card> : <div className="notification-list">
      {items.map((item) => <article key={item.id} className={`notification-item ${item.read_at ? '' : 'notification-item--unread'}`}>
        <NotificationIcon kind={item.kind} />
        <div className="notification-item__content">
          <div className="notification-item__meta"><span>{item.kind === 'release' ? 'Новая версия' : 'Сообщение'}</span><time dateTime={item.created_at}>{timeLabel(item.created_at)}</time></div>
          <h2>{item.title}</h2>
          <p className="notification-body">{item.body}</p>
          <div className="notification-item__actions">
            {item.kind === 'release' && item.release_note_id && <Link className="notification-detail-link" to={`/release-notes/${item.release_note_id}`}>О релизе <ArrowRight aria-hidden="true" /></Link>}
            {!item.read_at && <button className="notification-read-button" type="button" disabled={read.isPending || readAll.isPending} onClick={() => read.mutate(item.id)}><Check aria-hidden="true" /> Отметить прочитанным</button>}
          </div>
        </div>
        {!item.read_at && <span className="notification-unread-dot" aria-label="Не прочитано" />}
      </article>)}
      {(read.isError || readAll.isError) && <div className="form-alert" role="alert">{read.error?.message ?? readAll.error?.message}</div>}
      {inbox.hasNextPage && <Button variant="secondary" disabled={inbox.isFetchingNextPage} onClick={() => inbox.fetchNextPage()}>{inbox.isFetchingNextPage ? 'Загружаем…' : 'Показать ещё'}</Button>}
      <p className="notification-list-count">Показаны {items.length} из {inbox.data?.pages[0]?.total ?? 0}</p>
    </div>}
  </section>
}

function ReleaseHistory() {
  const notes = useQuery<ReleaseNote[]>({ queryKey: ['release-notes', 'published'], queryFn: () => api('/release-notes') })
  if (notes.isLoading) return <State kind="loading" title="Загружаем историю версий" />
  if (notes.isError) return <State kind="error" title="Не удалось загрузить историю">{notes.error.message}</State>
  if (!notes.data?.length) return <Card className="notification-empty"><State title="Заметок о релизах пока нет" /></Card>
  return <div className="notification-list">{notes.data.map((note) => <article key={note.id} className="notification-item notification-item--history">
    <NotificationIcon kind="release" />
    <div className="notification-item__content">
      <div className="notification-item__meta"><span>Версия {note.release_version}</span><time dateTime={note.published_at ?? note.created_at}>{dateLabel(note.published_at ?? note.created_at)}</time></div>
      <h2>{note.title}</h2>
      <p className="notification-body">{note.summary}</p>
      <Link className="notification-detail-link" to={`/release-notes/${note.id}`}>Читать о версии <ArrowRight aria-hidden="true" /></Link>
    </div>
  </article>)}</div>
}

export function ReleaseNotePage() {
  const { id } = useParams()
  const numericId = Number(id)
  const validId = Number.isInteger(numericId) && numericId > 0
  const note = useQuery<ReleaseNote>({
    queryKey: ['release-notes', 'detail', numericId],
    queryFn: () => api(`/release-notes/${numericId}`),
    enabled: validId,
    retry: false,
  })
  return <div className="page release-note-page">
    <Link className="release-note-back" to="/notifications?tab=releases"><ArrowLeft aria-hidden="true" /> К истории версий</Link>
    {!validId ? <State kind="error" title="Заметка не найдена" /> : note.isLoading ? <State kind="loading" title="Загружаем заметку" /> : note.isError ? <State kind="error" title="Не удалось открыть заметку">{note.error.message}</State> : note.data && <article className="release-note-document">
      <header className="release-note-document__header">
        <span className="release-note-version"><Sparkles aria-hidden="true" /> Версия {note.data.release_version}</span>
        <h1>{note.data.title}</h1>
        <p>{note.data.summary}</p>
        <time dateTime={note.data.published_at ?? note.data.created_at}>Опубликовано {dateLabel(note.data.published_at ?? note.data.created_at)}</time>
      </header>
      <ReleaseArticle body={note.data.body} />
    </article>}
  </div>
}
