import { useState, type FormEvent } from 'react'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, Check, FileText, Send } from 'lucide-react'
import { api, jsonBody } from '../lib/api'
import type { ListResponse, User } from '../lib/types'
import { Badge, Button, Card, Field, Input, PageHeader, Select, State } from '../components/ui'
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
  body: string
  status: 'draft' | 'published'
  created_at: string
  updated_at: string
  published_at: string | null
}
interface PrivateUser { id: number; username: string; active: boolean }
type Tab = 'inbox' | 'releases' | 'manage'
type Draft = { release_version: string; title: string; body: string }
const emptyDraft: Draft = { release_version: '', title: '', body: '' }

function timeLabel(value: string) {
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(value))
}

export function NotificationsPage() {
  const [tab, setTab] = useState<Tab>('inbox')
  const me = useQuery<User>({ queryKey: ['me'], queryFn: () => api('/auth/me') })
  return <div className="page notifications-page">
    <PageHeader eyebrow="Связь" title="Уведомления" description="Сообщения владельца и новости версий приложения." />
    <div className="notification-tabs" role="tablist" aria-label="Разделы уведомлений">
      <button role="tab" aria-selected={tab === 'inbox'} className={tab === 'inbox' ? 'active' : ''} onClick={() => setTab('inbox')}><Bell /> Входящие</button>
      <button role="tab" aria-selected={tab === 'releases'} className={tab === 'releases' ? 'active' : ''} onClick={() => setTab('releases')}><FileText /> История версий</button>
      {me.data?.is_admin && <button role="tab" aria-selected={tab === 'manage'} className={tab === 'manage' ? 'active' : ''} onClick={() => setTab('manage')}><Send /> Публикация</button>}
    </div>
    {tab === 'inbox' && <InboxView />}
    {tab === 'releases' && <ReleaseHistory />}
    {tab === 'manage' && me.data?.is_admin && <ManageView />}
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
  const read = useMutation({
    mutationFn: (id: number) => api(`/notifications/${id}/read`, { method: 'POST' }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['notifications', 'list'] }),
        client.invalidateQueries({ queryKey: ['notifications', 'count'] }),
      ])
    },
  })
  if (inbox.isLoading) return <State kind="loading" title="Загружаем уведомления" />
  if (inbox.isError) return <State kind="error" title="Не удалось загрузить уведомления">{inbox.error.message}</State>
  if (!items.length) return <Card><State title="Пока нет сообщений">Здесь появятся уведомления владельца и новости релизов.</State></Card>
  return <div className="notification-list">
    {items.map((item) => <Card key={item.id} className={`notification-item ${item.read_at ? '' : 'notification-item--unread'}`}>
      <div className="notification-item__head"><div><span className="eyebrow">{item.kind === 'release' ? 'Новая версия' : 'Сообщение'}</span><h2>{item.title}</h2></div>{item.read_at ? <Badge>Прочитано</Badge> : <Badge tone="info">Новое</Badge>}</div>
      <p className="notification-body">{item.body}</p>
      <div className="notification-item__foot"><small>{timeLabel(item.created_at)}</small>{!item.read_at && <Button variant="secondary" disabled={read.isPending} onClick={() => read.mutate(item.id)}><Check /> Прочитано</Button>}</div>
    </Card>)}
    {read.isError && <div className="form-alert" role="alert">{read.error.message}</div>}
    {inbox.hasNextPage && <Button variant="secondary" disabled={inbox.isFetchingNextPage} onClick={() => inbox.fetchNextPage()}>{inbox.isFetchingNextPage ? 'Загружаем…' : 'Показать ещё'}</Button>}
    <p className="form-hint">Показаны {items.length} из {inbox.data?.pages[0]?.total ?? 0} уведомлений.</p>
  </div>
}

function ReleaseHistory() {
  const notes = useQuery<ReleaseNote[]>({ queryKey: ['release-notes', 'published'], queryFn: () => api('/release-notes') })
  if (notes.isLoading) return <State kind="loading" title="Загружаем историю версий" />
  if (notes.isError) return <State kind="error" title="Не удалось загрузить историю">{notes.error.message}</State>
  if (!notes.data?.length) return <Card><State title="Заметок о релизах пока нет" /></Card>
  return <div className="notification-list">{notes.data.map((note) => <Card key={note.id} className="notification-item">
    <span className="eyebrow">Версия {note.release_version}</span><h2>{note.title}</h2>
    <p className="notification-body">{note.body}</p><small>{timeLabel(note.published_at ?? note.created_at)}</small>
  </Card>)}</div>
}

function ManageView() {
  const client = useQueryClient()
  const users = useQuery<ListResponse<PrivateUser>>({ queryKey: ['private-users'], queryFn: () => api('/users') })
  const notes = useQuery<ReleaseNote[]>({ queryKey: ['release-notes', 'manage'], queryFn: () => api('/release-notes/manage') })
  const [recipient, setRecipient] = useState('all')
  const [messageTitle, setMessageTitle] = useState('')
  const [messageBody, setMessageBody] = useState('')
  const [messageResult, setMessageResult] = useState('')
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [releaseResult, setReleaseResult] = useState('')
  const send = useMutation({
    mutationFn: () => api<{ delivered: number }>('/notifications/send', {
      method: 'POST', body: jsonBody({
        title: messageTitle, body: messageBody,
        recipient_user_id: recipient === 'all' ? null : Number(recipient),
      }),
    }),
    onSuccess: async (result) => {
      setMessageTitle(''); setMessageBody('')
      setMessageResult(`Доставлено: ${result.delivered}`)
      await Promise.all([
        client.invalidateQueries({ queryKey: ['notifications', 'list'] }),
        client.invalidateQueries({ queryKey: ['notifications', 'count'] }),
      ])
    },
  })
  const save = useMutation({
    mutationFn: () => api<ReleaseNote>(editingId === null ? '/release-notes' : `/release-notes/${editingId}`, {
      method: editingId === null ? 'POST' : 'PATCH', body: jsonBody(draft),
    }),
    onSuccess: async () => {
      setDraft(emptyDraft); setEditingId(null); setReleaseResult('Черновик сохранён')
      await client.invalidateQueries({ queryKey: ['release-notes', 'manage'] })
    },
  })
  const publish = useMutation({
    mutationFn: (id: number) => api<{ delivered: number }>(`/release-notes/${id}/publish`, { method: 'POST' }),
    onSuccess: async (result) => {
      setReleaseResult(`Заметка опубликована. Уведомлений доставлено: ${result.delivered}`)
      await Promise.all([
        client.invalidateQueries({ queryKey: ['release-notes'] }),
        client.invalidateQueries({ queryKey: ['notifications'] }),
      ])
    },
  })
  const submitMessage = (event: FormEvent) => { event.preventDefault(); setMessageResult(''); send.mutate() }
  const submitDraft = (event: FormEvent) => { event.preventDefault(); setReleaseResult(''); save.mutate() }
  return <div className="notification-management">
    <Card><div className="section-head"><div><span className="eyebrow">Владелец</span><h2>Отправить сообщение</h2></div></div>
      <form className="form-stack" onSubmit={submitMessage}>
        <Field label="Получатели"><Select value={recipient} onChange={(event) => setRecipient(event.target.value)}><option value="all">Все активные пользователи</option>{users.data?.items.filter((user) => user.active).map((user) => <option value={user.id} key={user.id}>{user.username}</option>)}</Select></Field>
        <Field label="Заголовок"><Input maxLength={160} required value={messageTitle} onChange={(event) => setMessageTitle(event.target.value)} /></Field>
        <Field label="Сообщение"><textarea className="input" rows={5} maxLength={20000} required value={messageBody} onChange={(event) => setMessageBody(event.target.value)} /></Field>
        {users.isError && <div className="form-alert" role="alert">{users.error.message}</div>}
        {send.isError && <div className="form-alert" role="alert">{send.error.message}</div>}
        {messageResult && <div className="notice notice--calm" role="status">{messageResult}</div>}
        <div className="form-actions"><Button type="submit" disabled={send.isPending || !messageTitle.trim() || !messageBody.trim() || users.isLoading}>Отправить</Button></div>
      </form>
    </Card>
    <Card><div className="section-head"><div><span className="eyebrow">Перед релизом</span><h2>Release notes</h2></div></div>
      <p>Сохраните заметку как черновик, проверьте текст и опубликуйте после выхода версии. Публикация отправит уведомление всем активным пользователям.</p>
      <form className="form-stack" onSubmit={submitDraft}>
        <Field label="Версия"><Input maxLength={40} pattern="[0-9A-Za-z][0-9A-Za-z._-]*" required value={draft.release_version} onChange={(event) => setDraft({ ...draft, release_version: event.target.value })} placeholder="Например, 1.4.0" /></Field>
        <Field label="Заголовок"><Input maxLength={160} required value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></Field>
        <Field label="Что изменилось"><textarea className="input" rows={8} maxLength={20000} required value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} placeholder="Короткие пункты о новых возможностях и исправлениях" /></Field>
        {save.isError && <div className="form-alert" role="alert">{save.error.message}</div>}
        {publish.isError && <div className="form-alert" role="alert">{publish.error.message}</div>}
        {releaseResult && <div className="notice notice--calm" role="status">{releaseResult}</div>}
        <div className="form-actions"><Button type="submit" disabled={save.isPending || !draft.release_version.trim() || !draft.title.trim() || !draft.body.trim()}>{editingId === null ? 'Сохранить черновик' : 'Сохранить изменения'}</Button>{editingId !== null && <Button type="button" variant="ghost" onClick={() => { setEditingId(null); setDraft(emptyDraft) }}>Отмена</Button>}</div>
      </form>
      <div className="notification-drafts">
        <h3>Заметки о версиях</h3>
        {notes.isLoading && <State kind="loading" title="Загружаем заметки" />}
        {notes.isError && <div className="form-alert" role="alert">{notes.error.message}</div>}
        {notes.data?.map((note) => <div className="notification-draft" key={note.id}>
          <div><strong>{note.release_version} · {note.title}</strong><small>{note.status === 'draft' ? 'Черновик' : `Опубликовано ${timeLabel(note.published_at ?? note.created_at)}`}</small></div>
          {note.status === 'draft' && <div className="notification-draft__actions"><Button variant="ghost" onClick={() => { setEditingId(note.id); setDraft({ release_version: note.release_version, title: note.title, body: note.body }); setReleaseResult('') }}>Изменить</Button><Button variant="secondary" disabled={publish.isPending} onClick={() => { if (window.confirm(`Опубликовать заметку версии ${note.release_version} и уведомить пользователей?`)) publish.mutate(note.id) }}>Опубликовать</Button></div>}
        </div>)}
      </div>
    </Card>
  </div>
}
