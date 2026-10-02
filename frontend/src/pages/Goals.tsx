import { useState, type CSSProperties } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Archive, CirclePlus, Flag, MoveDown, MoveUp, Pencil, Receipt, Trash2, Undo2 } from 'lucide-react'
import { ApiError, api, asList, jsonBody } from '../lib/api'
import { dateLabel, formatMoney, parseMoney, todayISO } from '../lib/format'
import type { Account, Category, Goal, ListResponse } from '../lib/types'
import { Badge, Button, Card, ErrorState, Field, Input, Modal, PageHeader, Progress, Select, State } from '../components/ui'
import { colorSchemeAccents, useTheme } from '../lib/theme'

const goalSchema = z.object({
  name: z.string().trim().min(1, 'Укажите название'),
  target: z.string().min(1, 'Укажите целевую сумму'),
  reserved: z.string().default('0'),
  deadline: z.string().optional(),
  priority: z.coerce.number().int().min(1).max(5),
  color: z.string(),
}).superRefine((values, context) => {
  for (const [field, value] of [['target', values.target], ['reserved', values.reserved]] as const) {
    try {
      if (parseMoney(value) < 0) throw new Error()
    } catch {
      context.addIssue({ code: z.ZodIssueCode.custom, path: [field], message: 'Укажите неотрицательную сумму' })
    }
  }
})

function archiveSchema(hasReserve: boolean) {
  return z.object({
    reserve_disposition: z.enum(['keep', 'release']).optional(),
    reserve_date: z.string().optional(),
  }).superRefine((values, context) => {
    if (hasReserve && !values.reserve_disposition) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ['reserve_disposition'], message: 'Выберите, что сделать с резервом' })
    }
    if (values.reserve_disposition === 'release' && !values.reserve_date) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ['reserve_date'], message: 'Укажите дату освобождения' })
    }
  })
}

const movementSchema = z.object({
  amount: z.string().min(1, 'Укажите сумму больше нуля'),
  kind: z.enum(['allocation', 'release', 'expense', 'refund']),
  date: z.string().min(1, 'Укажите дату'),
  account_id: z.string().optional(),
  category_id: z.string().optional(),
  description: z.string().max(300, 'Не больше 300 символов').optional(),
  comment: z.string().max(4000, 'Не больше 4000 символов').optional(),
  allow_allocate_shortfall: z.boolean().default(false),
}).superRefine((values, context) => {
  try {
    if (parseMoney(values.amount) <= 0) throw new Error()
  } catch {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['amount'], message: 'Укажите сумму больше нуля' })
  }
  if ((values.kind === 'expense' || values.kind === 'refund') && !values.account_id) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['account_id'], message: 'Выберите счёт' })
  }
})

type GoalValues = z.infer<typeof goalSchema>
type ArchiveValues = z.infer<ReturnType<typeof archiveSchema>>
type MovementValues = z.infer<typeof movementSchema>
type MovementSubmission = MovementValues & { idempotencyKey: string }
type ManagedGoal = Goal & { version: number; archived?: boolean }

function moneyInput(valueMinor: number) {
  return (valueMinor / 100).toFixed(2).replace('.', ',')
}

function refreshGoalQueries(client: ReturnType<typeof useQueryClient>) {
  void Promise.all([
    client.invalidateQueries({ queryKey: ['goals'] }),
    client.invalidateQueries({ queryKey: ['forecast'] }),
    client.invalidateQueries({ queryKey: ['analytics'] }),
  ])
}

function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return `goal-movement-${crypto.randomUUID()}`
  return `goal-movement-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function GoalsPage() {
  const [showArchived, setShowArchived] = useState(false)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<ManagedGoal | null>(null)
  const [archiving, setArchiving] = useState<ManagedGoal | null>(null)
  const [deleting, setDeleting] = useState<ManagedGoal | null>(null)
  const [moving, setMoving] = useState<Goal | null>(null)
  const client = useQueryClient()
  const goals = useQuery<ManagedGoal[] | ListResponse<ManagedGoal>>({
    queryKey: ['goals', { includeArchived: showArchived }],
    queryFn: () => api(showArchived ? '/goals?include_archived=true' : '/goals'),
  })
  const accounts = useQuery<Account[] | ListResponse<Account>>({ queryKey: ['accounts'], queryFn: () => api('/accounts') })
  const categories = useQuery<Category[] | ListResponse<Category>>({ queryKey: ['categories'], queryFn: () => api('/categories') })
  const create = useMutation({
    mutationFn: (v: GoalValues) => api('/goals', {
      method: 'POST',
      body: jsonBody({
        name: v.name,
        target_amount_minor: parseMoney(v.target),
        initial_reserved_minor: parseMoney(v.reserved),
        target_date: v.deadline || null,
        priority: v.priority,
        color: v.color,
      }),
    }),
    onSuccess: () => {
      refreshGoalQueries(client)
      setCreating(false)
    },
  })
  const update = useMutation<unknown, Error, { goal: ManagedGoal; values: GoalValues }>({
    mutationFn: ({ goal, values }) => api(`/goals/${goal.id}`, {
      method: 'PATCH',
      body: jsonBody({
        version: goal.version,
        name: values.name.trim(),
        target_amount_minor: parseMoney(values.target),
        target_date: values.deadline || null,
        priority: values.priority,
        color: values.color,
      }),
    }),
    onSuccess: () => {
      refreshGoalQueries(client)
      setEditing(null)
    },
  })
  const archive = useMutation<unknown, Error, { goal: ManagedGoal; values: ArchiveValues }>({
    mutationFn: ({ goal, values }) => api(`/goals/${goal.id}`, {
      method: 'PATCH',
      body: jsonBody({
        version: goal.version,
        status: 'archived',
        archived: true,
        ...(goal.reserved_minor > 0 ? {
          reserve_disposition: values.reserve_disposition,
          ...(values.reserve_disposition === 'release' ? { reserve_date: values.reserve_date } : {}),
        } : {}),
      }),
    }),
    onSuccess: () => {
      refreshGoalQueries(client)
      setArchiving(null)
    },
  })
  const restore = useMutation<unknown, Error, ManagedGoal>({
    mutationFn: (goal) => api(`/goals/${goal.id}`, {
      method: 'PATCH',
      body: jsonBody({ version: goal.version, status: 'active', archived: false }),
    }),
    onSuccess: () => refreshGoalQueries(client),
  })
  const remove = useMutation<unknown, Error, ManagedGoal>({
    mutationFn: (goal) => api(`/goals/${goal.id}?version=${encodeURIComponent(goal.version)}`, { method: 'DELETE' }),
    onSuccess: () => {
      refreshGoalQueries(client)
      setDeleting(null)
    },
  })

  return <div className="page">
    <PageHeader eyebrow="Накопления" title="Цели" description="Резерв — часть денег на ваших счетах, а не отдельный новый актив." actions={<Button onClick={() => { create.reset(); setCreating(true) }}><CirclePlus /> Добавить цель</Button>} />
    <div className="notice notice--calm"><Flag /><div><strong>Резервы не увеличивают общий баланс</strong><span>Свободные деньги равны остаткам на счетах за вычетом суммы всех резервов.</span></div></div>
    <label className="toggle-row"><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} /> Показывать архивные цели</label>
    {restore.isError && <div className="form-alert" role="alert">{restore.error.message}</div>}
    {goals.isLoading && <State kind="loading" title="Загружаем цели" />}
    {goals.isError && <ErrorState error={goals.error} retry={() => goals.refetch()} />}
    {goals.data && (asList(goals.data).length ? <div className="goal-grid">{asList(goals.data).map((goal) => {
      const target = goal.target_amount_minor ?? goal.target_minor ?? 0
      const need = goal.remaining_need_minor ?? Math.max(0, target - goal.reserved_minor)
      const complete = target > 0 ? goal.reserved_minor / target * 100 : 0
      return <Card className="goal-card" key={goal.id}>
        <div className="goal-top"><span className="goal-icon" style={{ '--goal-color': goal.color || 'var(--green)' } as CSSProperties}><Flag /></span>{goal.status && <Badge tone={goal.archived || goal.status === 'archived' ? 'neutral' : goal.status === 'completed' ? 'good' : 'info'}>{goal.archived || goal.status === 'archived' ? 'Архив' : goal.status === 'completed' ? 'Достигнута' : 'В процессе'}</Badge>}</div>
        <h2>{goal.name}</h2>
        <div className="goal-amount"><strong>{formatMoney(goal.reserved_minor)}</strong><span>из {formatMoney(target)}</span></div>
        <Progress value={goal.reserved_minor} max={target} tone={goal.color || 'var(--green)'} />
        <div className="goal-stats"><div><span>Осталось</span><strong>{formatMoney(need)}</strong></div><div><span>Срок</span><strong>{dateLabel(goal.target_date ?? goal.deadline)}</strong></div></div>
        {goal.recommended_contribution_minor != null && <div className="recommendation">Рекомендуемый взнос: <b>{formatMoney(goal.recommended_contribution_minor)}</b></div>}
        <div className="goal-actions">{!goal.archived && goal.status !== 'archived' && <Button variant="secondary" onClick={() => setMoving(goal)}><MoveDown /> Изменить резерв</Button>}<span>{Math.round(complete)}%</span></div>
        <div className="row-actions" style={{ marginTop: 8, flexWrap: 'wrap', gap: 2 }}>
          <Button variant="ghost" aria-label={`Редактировать цель ${goal.name}`} onClick={() => { update.reset(); setEditing(goal) }}><Pencil /> Изменить</Button>
          {goal.archived || goal.status === 'archived'
            ? <Button variant="secondary" aria-label={`Восстановить цель ${goal.name}`} disabled={restore.isPending && restore.variables?.id === goal.id} onClick={() => { restore.reset(); restore.mutate(goal) }}><Undo2 /> Восстановить</Button>
            : <Button variant="ghost" aria-label={`Архивировать цель ${goal.name}`} onClick={() => { archive.reset(); setArchiving(goal) }}><Archive /> В архив</Button>}
          <Button variant="ghost" aria-label={`Удалить цель ${goal.name}`} title="Только для цели без резервов и истории" onClick={() => { remove.reset(); setDeleting(goal) }}><Trash2 /></Button>
        </div>
      </Card>
    })}</div> : <State title="Целей пока нет">Добавьте отпуск, крупную покупку или финансовую подушку.</State>)}
    {creating && <GoalForm mutation={create} onClose={() => setCreating(false)} />}
    {editing && <GoalForm
      goal={editing}
      mutation={{
        mutate: (values) => update.mutate({ goal: editing, values }),
        isPending: update.isPending,
        isError: update.isError,
        error: update.error,
      }}
      onClose={() => setEditing(null)}
    />}
    {archiving && <ArchiveGoalForm goal={archiving} mutation={archive} onClose={() => setArchiving(null)} />}
    {deleting && <DeleteGoalForm
      goal={deleting}
      mutation={remove}
      onClose={() => setDeleting(null)}
      onArchive={() => {
        const goal = deleting
        setDeleting(null)
        remove.reset()
        archive.reset()
        setArchiving(goal)
      }}
    />}
    {moving && <MovementForm
      goal={moving}
      accounts={asList(accounts.data)}
      categories={asList(categories.data)}
      referencesLoading={accounts.isLoading || categories.isLoading}
      referencesError={accounts.isError || categories.isError}
      onClose={() => setMoving(null)}
    />}
  </div>
}

function GoalForm({ goal, mutation, onClose }: {
  goal?: ManagedGoal
  mutation: Pick<ReturnType<typeof useMutation<unknown, Error, GoalValues>>, 'mutate' | 'isPending' | 'isError' | 'error'>
  onClose: () => void
}) {
  const { colorScheme } = useTheme()
  const defaultColor = colorSchemeAccents[colorScheme]
  const target = goal?.target_amount_minor ?? goal?.target_minor ?? 0
  const { register, handleSubmit, formState: { errors } } = useForm<GoalValues>({
    resolver: zodResolver(goalSchema),
    defaultValues: goal ? {
      name: goal.name,
      target: moneyInput(target),
      reserved: '0',
      deadline: goal.target_date ?? goal.deadline ?? '',
      priority: goal.priority && goal.priority >= 1 && goal.priority <= 5 ? goal.priority : 3,
      color: goal.color || defaultColor,
    } : { reserved: '0', priority: 3, color: defaultColor },
  })
  return <Modal title={goal ? `Изменить цель «${goal.name}»` : 'Новая цель'} onClose={onClose}><form className="form-grid" onSubmit={handleSubmit((v) => mutation.mutate(v))}>
    <Field label="Название" error={errors.name?.message}><Input autoFocus {...register('name')} placeholder="Например, отпуск" /></Field>
    <Field label="Целевая сумма" error={errors.target?.message}><Input inputMode="decimal" {...register('target')} placeholder="150 000" /></Field>
    {!goal && <Field label="Уже зарезервировано" error={errors.reserved?.message} hint="Сумма будет выделена из существующих остатков"><Input inputMode="decimal" {...register('reserved')} /></Field>}
    <Field label="Срок"><Input type="date" {...register('deadline')} /></Field>
    <Field label="Приоритет"><Select {...register('priority')}><option value="1">1 — высокий</option><option value="2">2</option><option value="3">3 — обычный</option><option value="4">4</option><option value="5">5 — низкий</option></Select></Field>
    <Field label="Цвет"><Input type="color" {...register('color')} /></Field>
    {mutation.isError && <div className="form-alert form-span">{mutation.error?.message}</div>}
    <div className="form-actions form-span"><Button variant="ghost" type="button" onClick={onClose}>Отмена</Button><Button disabled={mutation.isPending}>{mutation.isPending ? 'Сохраняем…' : goal ? 'Сохранить' : 'Создать цель'}</Button></div>
  </form></Modal>
}

function ArchiveGoalForm({ goal, mutation, onClose }: {
  goal: ManagedGoal
  mutation: ReturnType<typeof useMutation<unknown, Error, { goal: ManagedGoal; values: ArchiveValues }>>
  onClose: () => void
}) {
  const hasReserve = goal.reserved_minor > 0
  const { register, handleSubmit, watch, formState: { errors } } = useForm<ArchiveValues>({
    resolver: zodResolver(archiveSchema(hasReserve)),
    defaultValues: { reserve_date: '' },
  })
  const disposition = watch('reserve_disposition')
  return <Modal title={`Архивировать цель «${goal.name}»?`} onClose={onClose}>
    <form className="form-stack" onSubmit={handleSubmit((values) => mutation.mutate({ goal, values }))}>
      <div className="notice notice--danger"><Archive /><div><strong>Цель исчезнет из активных</strong><span>История и операции сохранятся.{hasReserve ? ` Выберите, как поступить с резервом ${formatMoney(goal.reserved_minor)}.` : ''}</span></div></div>
      {hasReserve && <>
        <div role="group" aria-label="Судьба резерва">
          <label className="import-confirm-option"><input type="radio" value="keep" {...register('reserve_disposition')} /><span><strong>Сохранить резерв</strong><small>Деньги останутся закреплены за архивной целью.</small></span></label>
          <label className="import-confirm-option"><input type="radio" value="release" {...register('reserve_disposition')} /><span><strong>Освободить резерв</strong><small>Деньги вернутся в свободный остаток в указанную дату.</small></span></label>
        </div>
        {errors.reserve_disposition && <div className="form-alert" role="alert">Выберите, что сделать с резервом</div>}
        {disposition === 'release' && <Field label="Дата освобождения" error={errors.reserve_date?.message}><Input type="date" autoFocus {...register('reserve_date')} /></Field>}
      </>}
      {mutation.isError && <div className="form-alert">{mutation.error?.message}</div>}
      <div className="form-actions"><Button variant="ghost" type="button" onClick={onClose}>Отмена</Button><Button variant="danger" disabled={mutation.isPending}>{mutation.isPending ? 'Архивируем…' : 'Архивировать'}</Button></div>
    </form>
  </Modal>
}

function DeleteGoalForm({ goal, mutation, onClose, onArchive }: {
  goal: ManagedGoal
  mutation: ReturnType<typeof useMutation<unknown, Error, ManagedGoal>>
  onClose: () => void
  onArchive: () => void
}) {
  const hasHistory = mutation.error instanceof ApiError
    && mutation.error.status === 409
    && /reserve|history|archive/i.test(mutation.error.message)
  return <Modal title={`Удалить цель «${goal.name}»?`} onClose={onClose}>
    <div className="form-stack">
      <div className="notice notice--danger"><Trash2 /><div><strong>Это действие нельзя отменить</strong><span>Удаление доступно только для цели без резерва, движений, операций и планов.</span></div></div>
      {mutation.isError && <div className="form-alert" role="alert">{hasHistory ? 'У цели есть резерв или история, поэтому её можно только архивировать.' : mutation.error?.message}</div>}
      <div className="form-actions">
        <Button variant="ghost" type="button" onClick={onClose}>Отмена</Button>
        {hasHistory && <Button variant="secondary" type="button" onClick={onArchive}><Archive /> Архивировать вместо удаления</Button>}
        {!hasHistory && <Button variant="danger" type="button" disabled={mutation.isPending} onClick={() => mutation.mutate(goal)}>{mutation.isPending ? 'Удаляем…' : 'Удалить навсегда'}</Button>}
      </div>
    </div>
  </Modal>
}

function MovementForm({ goal, accounts, categories, referencesLoading, referencesError, onClose }: {
  goal: Goal
  accounts: Account[]
  categories: Category[]
  referencesLoading: boolean
  referencesError: boolean
  onClose: () => void
}) {
  const client = useQueryClient()
  const { register, handleSubmit, watch, formState: { errors } } = useForm<MovementValues>({
    resolver: zodResolver(movementSchema),
    defaultValues: {
      kind: 'allocation',
      date: todayISO(),
      account_id: '',
      category_id: '',
      description: '',
      comment: '',
      allow_allocate_shortfall: false,
    },
  })
  const kind = watch('kind')
  const usesAccount = kind === 'expense' || kind === 'refund'
  const activeAccounts = accounts.filter((account) => !account.archived)
  const expenseCategories = categories.filter((category) => !category.archived && (category.kind ?? category.type) === 'expense')
  const mutation = useMutation({
    mutationFn: ({ idempotencyKey, ...values }: MovementSubmission) => {
      const body: Record<string, unknown> = {
        kind: values.kind,
        amount_minor: parseMoney(values.amount),
        date: values.date,
        comment: values.comment?.trim() || null,
      }
      if (values.kind === 'expense' || values.kind === 'refund') {
        body.account_id = Number(values.account_id)
        body.category_id = values.category_id ? Number(values.category_id) : null
        body.description = values.description?.trim() || ''
      }
      if (values.kind === 'expense') body.allow_allocate_shortfall = values.allow_allocate_shortfall
      return api(`/goals/${goal.id}/allocations`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: jsonBody(body),
      })
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['goals'] })
      client.invalidateQueries({ queryKey: ['forecast'] })
      client.invalidateQueries({ queryKey: ['accounts'] })
      client.invalidateQueries({ queryKey: ['/transactions'] })
      client.invalidateQueries({ queryKey: ['analytics'] })
      onClose()
    },
  })
  const reserveExplanation = {
    allocation: 'Выделение переносит деньги из свободных в резерв. Общий остаток на счетах не меняется.',
    release: 'Освобождение возвращает деньги из резерва в свободные. Общий остаток на счетах не меняется.',
    expense: 'Оплата уменьшит деньги на выбранном счёте и резерв на одну сумму. Свободные деньги не уменьшатся повторно.',
    refund: 'Возврат увеличит деньги на выбранном счёте и восстановит резерв. Он не считается новым доходом.',
  }[kind]

  return <Modal title={`Операция с целью: ${goal.name}`} onClose={onClose}><form className="form-stack" onSubmit={handleSubmit((values) => mutation.mutate({ ...values, idempotencyKey: newIdempotencyKey() }))}>
    <div className="segmented segmented--wide">
      <label className={kind === 'allocation' ? 'active' : ''}><input type="radio" value="allocation" {...register('kind')} /><MoveDown /> Выделить</label>
      <label className={kind === 'release' ? 'active' : ''}><input type="radio" value="release" {...register('kind')} /><MoveUp /> Освободить</label>
      <label className={kind === 'expense' ? 'active' : ''}><input type="radio" value="expense" {...register('kind')} /><Receipt /> Оплатить</label>
      <label className={kind === 'refund' ? 'active' : ''}><input type="radio" value="refund" {...register('kind')} /><Undo2 /> Вернуть</label>
    </div>
    <Field label="Сумма" error={errors.amount?.message}><Input inputMode="decimal" autoFocus {...register('amount')} placeholder="0,00" /></Field>
    <Field label="Дата" error={errors.date?.message}><Input type="date" {...register('date')} /></Field>
    {usesAccount && <>
      <Field label="Счёт" error={errors.account_id?.message} hint="Счёт списания или возврата"><Select {...register('account_id')}><option value="">Не выбран</option>{activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</Select></Field>
      <Field label="Категория расхода" hint="Необязательно; доступны только категории расходов"><Select {...register('category_id')}><option value="">Без категории</option>{expenseCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</Select></Field>
      <Field label="Описание операции"><Input {...register('description')} placeholder={kind === 'expense' ? 'Например, билеты' : 'Например, возврат билетов'} /></Field>
    </>}
    <Field label="Комментарий"><textarea className="input textarea" {...register('comment')} /></Field>
    {kind === 'expense' && <label className="import-confirm-option">
      <input type="checkbox" {...register('allow_allocate_shortfall')} />
      <span><strong>Разрешить покрыть нехватку резерва</strong><small>Если в резерве на выбранную дату не хватит денег, недостающая сумма будет явно выделена из свободных денег и потрачена атомарно.</small></span>
    </label>}
    <p className="form-hint">Сейчас в резерве: <strong>{formatMoney(goal.reserved_minor)}</strong>. {reserveExplanation}</p>
    {referencesLoading && usesAccount && <div className="form-hint">Загружаем счета и категории…</div>}
    {referencesError && usesAccount && <div className="form-alert">Не удалось загрузить счета или категории. Закройте форму и попробуйте ещё раз.</div>}
    {mutation.isError && <div className="form-alert">{mutation.error.message}</div>}
    <div className="form-actions"><Button variant="ghost" type="button" onClick={onClose}>Отмена</Button><Button disabled={mutation.isPending || (usesAccount && (referencesLoading || referencesError))}>{mutation.isPending ? 'Проводим…' : 'Подтвердить'}</Button></div>
  </form></Modal>
}
