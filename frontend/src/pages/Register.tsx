import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { UserPlus } from 'lucide-react'
import { api, jsonBody } from '../lib/api'
import { AuthIntro } from '../components/AuthIntro'
import { Button, Field, Input } from '../components/ui'
import type { User } from '../lib/types'

const schema = z.object({
  username: z.string().regex(/^[a-z][a-z0-9_.-]{2,79}$/, 'От 3 до 80 символов: латинские буквы, цифры, _, . и -; первый символ — буква'),
  password: z.string().min(12, 'Пароль должен содержать не менее 12 символов').max(512),
  confirmation: z.string().min(1, 'Повторите пароль'),
}).refine((values) => values.password === values.confirmation, {
  path: ['confirmation'], message: 'Пароли не совпадают',
})
type Values = z.infer<typeof schema>

export function Register({ currentUser }: { currentUser?: User | null }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const { register, handleSubmit, formState: { errors } } = useForm<Values>({ resolver: zodResolver(schema) })
  const create = useMutation({
    mutationFn: (values: Values) => api<{ user: User; csrf_token: string }>('/auth/register', {
      method: 'POST', body: jsonBody({ username: values.username, password: values.password }),
    }),
    onSuccess: (response) => { client.clear(); client.setQueryData(['me'], response.user); navigate('/') },
  })
  if (currentUser) return <Navigate to="/" replace />
  return <div className="login-page">
    <AuthIntro/>
    <section className="login-form-wrap">
      <form className="login-form" onSubmit={handleSubmit((values) => create.mutate(values))}>
        <div className="login-icon"><UserPlus/></div>
        <h2>Новый аккаунт</h2>
        <p>Создайте отдельный личный бюджет.</p>
        <Field label="Логин" error={errors.username?.message} hint="Латиница, цифры, _, . и -; от 3 символов">
          <Input autoComplete="username" autoFocus {...register('username')}/>
        </Field>
        <Field label="Пароль" error={errors.password?.message} hint="Не менее 12 символов">
          <Input type="password" autoComplete="new-password" {...register('password')}/>
        </Field>
        <Field label="Повторите пароль" error={errors.confirmation?.message}>
          <Input type="password" autoComplete="new-password" {...register('confirmation')}/>
        </Field>
        {create.isError && <div className="form-alert" role="alert">{create.error.message}</div>}
        <Button type="submit" disabled={create.isPending}>{create.isPending ? 'Создаём…' : 'Создать аккаунт'}</Button>
        <small>Уже есть аккаунт? <Link to="/login">Войти</Link></small>
      </form>
    </section>
  </div>
}
