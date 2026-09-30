import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { LockKeyhole } from 'lucide-react'
import { api, jsonBody } from '../lib/api'
import { AuthIntro } from '../components/AuthIntro'
import { Button, Field, Input } from '../components/ui'
import type { User } from '../lib/types'

const schema = z.object({ username: z.string().min(1, 'Введите логин'), password: z.string().min(1, 'Введите пароль') })
type Values = z.infer<typeof schema>

export function Login({ currentUser }: { currentUser?: User | null }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const { register, handleSubmit, formState: { errors } } = useForm<Values>({ resolver: zodResolver(schema) })
  const login = useMutation({
    mutationFn: (values: Values) => api<{ user: User; csrf_token: string }>('/auth/login', { method: 'POST', body: jsonBody(values) }),
    onSuccess: (response) => { client.clear(); client.setQueryData(['me'], response.user); navigate('/') },
  })
  if (currentUser) return <Navigate to="/" replace />
  return <div className="login-page">
    <AuthIntro/>
    <section className="login-form-wrap">
      <form className="login-form" onSubmit={handleSubmit((values) => login.mutate(values))}>
        <div className="login-icon"><LockKeyhole/></div>
        <h2>Вход в бюджет</h2>
        <p>Введите свой логин и пароль.</p>
        <Field label="Логин" error={errors.username?.message}>
          <Input autoComplete="username" autoFocus {...register('username')}/>
        </Field>
        <Field label="Пароль" error={errors.password?.message}>
          <Input type="password" autoComplete="current-password" {...register('password')}/>
        </Field>
        {login.isError && <div className="form-alert" role="alert">{login.error.message}</div>}
        <Button type="submit" disabled={login.isPending}>{login.isPending ? 'Проверяем…' : 'Войти'}</Button>
        <small>Нет аккаунта? <Link to="/register">Зарегистрироваться</Link></small>
      </form>
    </section>
  </div>
}
