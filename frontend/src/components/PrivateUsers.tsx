import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CirclePlus, KeyRound, UserRound, UserRoundCheck, UserRoundX } from 'lucide-react'
import { api, asList, jsonBody } from '../lib/api'
import type { ListResponse } from '../lib/types'
import { Badge, Button, Card, Field, Input, Modal, State } from './ui'

interface PrivateUser { id: number; username: string; is_admin: boolean; active: boolean }

export function PrivateUsers() {
  const client = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [resetting, setResetting] = useState<PrivateUser | null>(null)
  const [notice, setNotice] = useState('')
  const users = useQuery<ListResponse<PrivateUser>>({ queryKey: ['private-users'], queryFn: () => api('/users') })
  const change = useMutation({
    mutationFn: ({ user, active }: { user: PrivateUser; active: boolean }) => api(`/users/${user.id}`, { method: 'PATCH', body: jsonBody({ active }) }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['private-users'] }) },
  })
  return <Card className="settings-card">
    <div className="section-head"><div><span className="eyebrow">Доступ</span><h2>Пользователи</h2></div><Button onClick={() => { setNotice(''); setCreating(true) }}><CirclePlus/> Добавить</Button></div>
    <p>Каждый пользователь получает отдельный приватный бюджет. Отключение входа сохраняет его данные и завершает его сессии.</p>
    {notice && <div className="notice notice--calm"><UserRoundCheck/><span>{notice}</span></div>}
    {change.isError && <div className="form-alert" role="alert">{change.error.message}</div>}
    {users.isLoading ? <State kind="loading" title="Загружаем пользователей"/> : users.isError ? <State kind="error" title="Не удалось загрузить пользователей"/> : <div className="directory-list">{asList(users.data).map((user) => <div key={user.id}><UserRound/><div><strong>{user.username}</strong><small>{user.is_admin ? 'Владелец' : 'Личный бюджет'} · {user.active ? 'Доступ открыт' : 'Доступ отключён'}</small></div>{!user.active && <Badge>Отключён</Badge>}<div className="directory-actions"><button className="icon-button" aria-label={`Сменить пароль ${user.username}`} title="Сменить пароль" onClick={() => { setNotice(''); setResetting(user) }}><KeyRound/></button>{!user.is_admin && <button className="icon-button" aria-label={`${user.active ? 'Отключить' : 'Включить'} ${user.username}`} title={user.active ? 'Отключить вход' : 'Включить вход'} onClick={() => { if (!user.active || window.confirm(`Отключить вход для ${user.username}? Бюджет сохранится.`)) change.mutate({ user, active: !user.active }) }}>{user.active ? <UserRoundX/> : <UserRoundCheck/>}</button>}</div></div>)}</div>}
    {creating && <PasswordForm title="Новый пользователь" onClose={() => setCreating(false)} onSaved={async () => { setCreating(false); setNotice('Пользователь создан. Передайте ему логин и заданный пароль.'); await client.invalidateQueries({ queryKey: ['private-users'] }) }} />}
    {resetting && <PasswordForm title={`Пароль: ${resetting.username}`} user={resetting} onClose={() => setResetting(null)} onSaved={async () => { const self = resetting.is_admin; setResetting(null); setNotice('Пароль изменён. Существующие сессии пользователя завершены.'); await client.invalidateQueries({ queryKey: ['private-users'] }); if (self) await client.invalidateQueries({ queryKey: ['me'] }) }} />}
  </Card>
}

function PasswordForm({ title, user, onClose, onSaved }: { title: string; user?: PrivateUser; onClose: () => void; onSaved: () => Promise<void> }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState('')
  const save = useMutation({
    mutationFn: () => api(user ? `/users/${user.id}/reset-password` : '/users', {
      method: 'POST', body: jsonBody(user ? { password } : { username: username.trim(), password }),
    }),
    onSuccess: onSaved,
  })
  const submit = () => {
    if (!user && !/^[a-z][a-z0-9_.-]{2,79}$/.test(username.trim())) { setError('Логин: от 3 символов, латинские строчные буквы, цифры, _, . или -'); return }
    if (password.length < 12) { setError('Пароль должен содержать не менее 12 символов'); return }
    if (password !== repeat) { setError('Пароли не совпадают'); return }
    setError('')
    save.mutate()
  }
  return <Modal title={title} onClose={onClose}><form className="form-stack" onSubmit={(event) => { event.preventDefault(); submit() }}>
    {!user && <Field label="Логин"><Input autoFocus autoComplete="off" value={username} onChange={(event) => setUsername(event.target.value.toLowerCase())}/></Field>}
    <Field label="Пароль"><Input type="password" autoFocus={Boolean(user)} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)}/></Field>
    <Field label="Повторите пароль"><Input type="password" autoComplete="new-password" value={repeat} onChange={(event) => setRepeat(event.target.value)}/></Field>
    <p className="form-hint">Пароль задаётся один раз и хранится в виде хеша. Созданный пользователь увидит только свой бюджет.</p>
    {(error || save.isError) && <div className="form-alert" role="alert">{error || save.error?.message}</div>}
    <div className="form-actions"><Button type="button" variant="ghost" onClick={onClose}>Отмена</Button><Button type="submit" disabled={save.isPending}>{save.isPending ? 'Сохраняем…' : user ? 'Сменить пароль' : 'Создать пользователя'}</Button></div>
  </form></Modal>
}
