import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Navigate, useNavigate } from 'react-router-dom'
import { LockKeyhole, ShieldCheck } from 'lucide-react'
import { api, jsonBody } from '../lib/api'
import { Button, Field, Input } from '../components/ui'
import type { User } from '../lib/types'

const schema = z.object({ username: z.string().min(1, 'Введите логин'), password: z.string().min(1, 'Введите пароль') })
type Values = z.infer<typeof schema>

export function Login({ currentUser }: { currentUser?: User | null }) {
  const navigate = useNavigate(); const client = useQueryClient()
  const { register, handleSubmit, formState: { errors } } = useForm<Values>({ resolver: zodResolver(schema) })
  const login = useMutation({
    mutationFn: (values: Values) => api<{ user: User; csrf_token: string }>('/auth/login', { method: 'POST', body: jsonBody(values) }),
    onSuccess: (response) => { client.setQueryData(['me'], response.user); navigate('/') },
  })
  if (currentUser) return <Navigate to="/" replace />
  return <div className="login-page">
    <section className="login-intro"><div className="brand brand--light"><div className="brand-mark">К</div><div className="brand-copy"><strong>Контур</strong><span>Личный бюджет</span></div></div><div><span className="login-kicker">Финансы без шума</span><h1>Каждый рубль<br/>на своём месте.</h1><p>Планируйте доходы, обязательства и большие цели — приватно, на своём сервере.</p></div><div className="privacy-note"><ShieldCheck/><span>Данные остаются у вас<br/><small>Без облака и банковских подключений</small></span></div></section>
    <section className="login-form-wrap"><form className="login-form" onSubmit={handleSubmit((v) => login.mutate(v))}><div className="login-icon"><LockKeyhole/></div><h2>Вход в бюджет</h2><p>Введите данные владельца, созданные при настройке.</p><Field label="Логин" error={errors.username?.message}><Input autoComplete="username" autoFocus {...register('username')} /></Field><Field label="Пароль" error={errors.password?.message}><Input type="password" autoComplete="current-password" {...register('password')} /></Field>{login.isError && <div className="form-alert">{login.error.message}</div>}<Button type="submit" disabled={login.isPending}>{login.isPending ? 'Проверяем…' : 'Войти'}</Button><small>Нет доступа? Сбросьте пароль локальной CLI-командой на сервере.</small></form></section>
  </div>
}
