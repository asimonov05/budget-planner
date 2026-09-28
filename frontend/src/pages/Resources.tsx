import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Archive, ArrowRight, Ban, CalendarPlus, CirclePlus, Pencil, RotateCcw, Search, Trash2 } from 'lucide-react'
import { ApiError, api, asList, jsonBody, queryString } from '../lib/api'
import { dateLabel, formatMoney, parseMoney } from '../lib/format'
import type { Account, Category, ID, ListResponse, Loan, LoanScheduleItem, Tag, Transaction, Transfer } from '../lib/types'
import { Badge, Button, ErrorState, Field, Input, Modal, PageHeader, Select, State } from '../components/ui'

type ResourceType = 'income' | 'payment' | 'transaction' | 'loan'
interface PlanItem {
  id: ID; kind: 'income' | 'expense'; title: string; amount_minor: number; date?: string; month?: string;
  start_date?: string; recurrence: string; certainty: string; status: string; account_id?: ID;
  category_id?: ID; tags?: Tag[]; comment?: string; end_date?: string; version?: number
}
type Item = PlanItem | Transaction | Loan
type EditableItem = Item | Transfer

const configs = {
  income: { eyebrow: 'Поступления', title: 'Доходы', description: 'Регулярная зарплата и разовые поступления.', add: 'Добавить доход', endpoint: '/plan-items', empty: 'Доходов пока нет' },
  payment: { eyebrow: 'Обязательства', title: 'Платежи и расходы', description: 'Ожидаемые платежи, лимиты и регулярные обязательства.', add: 'Добавить платеж', endpoint: '/plan-items', empty: 'Платежей пока нет' },
  transaction: { eyebrow: 'Факт', title: 'Операции', description: 'Фактические движения по счетам и сверка с планом.', add: 'Добавить операцию', endpoint: '/transactions', empty: 'Операций пока нет' },
  loan: { eyebrow: 'Обязательства', title: 'Кредиты', description: 'Графики платежей без подмены остатка основного долга.', add: 'Добавить кредит', endpoint: '/loans', empty: 'Кредитов пока нет' },
} satisfies Record<ResourceType, { eyebrow: string; title: string; description: string; add: string; endpoint: string; empty: string }>

const baseSchema = z.object({
  title: z.string().optional(), amount: z.string().optional(), date: z.string().optional(), month: z.string().optional(),
  account_id: z.string().optional(), category_id: z.string().optional(), recurrence: z.string().optional(), certainty: z.string().optional(),
  transaction_type: z.string().optional(), to_account_id: z.string().optional(), creditor: z.string().optional(), comment: z.string().optional(),
  principal_as_of: z.string().optional(), start_date: z.string().optional(), end_date: z.string().optional(), tag_ids: z.array(z.string()).optional(),
})
type FormValues = z.infer<typeof baseSchema>
interface ResourceSubmission { values: FormValues; idempotencyKey: string; item?: EditableItem }

function newIdempotencyKey(scope: string) {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `${scope}-${random}`
}

function numericIds(values?: string[]) { return (values ?? []).map(Number) }
function moneyInput(valueMinor: number) { return (valueMinor / 100).toFixed(2).replace('.', ',') }
function itemVersion(item: { version?: number }) { return item.version ?? 1 }
function actionError(error: Error | null) {
  if (!error) return null
  return error instanceof ApiError && error.status === 409
    ? `${error.message}. Обновите данные и повторите действие.`
    : error.message
}
function localDate() {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}

function schemaFor(type: ResourceType) {
  return baseSchema.superRefine((values, context) => {
    const isTransfer = type === 'transaction' && values.transaction_type === 'transfer'
    if (!isTransfer && !values.title?.trim()) context.addIssue({ code: z.ZodIssueCode.custom, path: ['title'], message: 'Укажите название' })
    if (type !== 'loan') {
      try {
        const amount = values.amount ? parseMoney(values.amount) : 0
        const signedAdjustment = type === 'transaction' && values.transaction_type === 'adjustment'
        if (signedAdjustment ? amount === 0 : amount <= 0) throw new Error()
      } catch {
        context.addIssue({ code: z.ZodIssueCode.custom, path: ['amount'], message: values.transaction_type === 'adjustment' ? 'Укажите ненулевую корректировку со знаком' : 'Укажите сумму больше нуля' })
      }
    } else if (values.amount) {
      try { parseMoney(values.amount) } catch { context.addIssue({ code: z.ZodIssueCode.custom, path: ['amount'], message: 'Проверьте сумму' }) }
    }
    if (type === 'transaction') {
      if (!values.date) context.addIssue({ code: z.ZodIssueCode.custom, path: ['date'], message: 'Укажите дату' })
      if (!values.account_id) context.addIssue({ code: z.ZodIssueCode.custom, path: ['account_id'], message: 'Выберите счёт' })
      if (isTransfer && !values.to_account_id) context.addIssue({ code: z.ZodIssueCode.custom, path: ['to_account_id'], message: 'Выберите счёт зачисления' })
      if (isTransfer && values.account_id && values.to_account_id === values.account_id) context.addIssue({ code: z.ZodIssueCode.custom, path: ['to_account_id'], message: 'Счета перевода должны отличаться' })
      if (values.transaction_type === 'adjustment' && !values.comment?.trim()) context.addIssue({ code: z.ZodIssueCode.custom, path: ['comment'], message: 'Для корректировки нужен комментарий' })
    }
    if ((type === 'income' || type === 'payment') && !values.date && !values.month) context.addIssue({ code: z.ZodIssueCode.custom, path: ['date'], message: 'Укажите дату или месяц' })
    if ((type === 'income' || type === 'payment') && values.recurrence !== 'none' && !values.date) context.addIssue({ code: z.ZodIssueCode.custom, path: ['date'], message: 'Для повторения нужна дата первого платежа' })
  })
}

function statusBadge(status?: string) {
  const labels: Record<string, string> = { planned: 'Запланирован', fulfilled: 'Исполнен', cancelled: 'Отменён', paid: 'Оплачен', partial: 'Частично', partially_paid: 'Частично оплачен', overdue: 'Просрочен', active: 'Активен', archived: 'В архиве' }
  const tone = status === 'fulfilled' || status === 'paid' ? 'good' : status === 'overdue' ? 'danger' : status === 'cancelled' ? 'neutral' : 'info'
  return <Badge tone={tone}>{labels[status ?? ''] ?? status ?? 'Активно'}</Badge>
}

function resourceName(item: Item) { return 'title' in item ? item.title : 'name' in item ? item.name : item.description || 'Операция' }
function resourceAmount(item: Item) { return 'amount_minor' in item ? item.amount_minor : item.next_payment_minor ?? item.remaining_payments_minor ?? item.principal_minor ?? 0 }
function resourceDate(item: Item) { return 'date' in item ? item.date : 'name' in item ? item.next_payment_date ?? item.start_date : undefined }

export function ResourcePage({ type }: { type: ResourceType }) {
  const config = configs[type]; const client = useQueryClient(); const [open, setOpen] = useState(false); const [editing, setEditing] = useState<EditableItem | null>(null); const [search, setSearch] = useState(''); const [page, setPage] = useState(1); const [scheduleLoan, setScheduleLoan] = useState<Loan | null>(null); const [matchingPlan, setMatchingPlan] = useState<PlanItem | null>(null); const [transferSaved, setTransferSaved] = useState(false)
  const pageSize = 100
  const filter = type === 'income' ? { kind: 'income' } : type === 'payment' ? { kind: 'expense' } : type === 'transaction' ? { limit: pageSize, offset: (page - 1) * pageSize } : { include_archived: true }
  const list = useQuery<Item[] | ListResponse<Item>>({ queryKey: [config.endpoint, filter], queryFn: () => api(`${config.endpoint}?${queryString(filter)}`) })
  const accounts = useQuery<Account[] | ListResponse<Account>>({ queryKey: ['accounts', { include_archived: true }], queryFn: () => api('/accounts?include_archived=true') })
  const categories = useQuery<Category[] | ListResponse<Category>>({ queryKey: ['categories', { include_archived: true }], queryFn: () => api('/categories?include_archived=true') })
  const tags = useQuery<Tag[] | ListResponse<Tag>>({ queryKey: ['tags', { include_archived: true }], queryFn: () => api('/tags?include_archived=true'), enabled: type !== 'loan' })
  const transfers = useQuery<Transfer[] | ListResponse<Transfer>>({ queryKey: ['/transfers'], queryFn: () => api('/transfers'), enabled: type === 'transaction' })
  const items = asList(list.data).filter((item) => resourceName(item).toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')))
  const accountNames = new Map(asList(accounts.data).map((account) => [String(account.id), account.name]))
  const transferItems = asList(transfers.data).filter((transfer) => {
    const label = `${accountNames.get(String(transfer.from_account_id)) ?? 'Счёт'} ${accountNames.get(String(transfer.to_account_id)) ?? 'Счёт'} ${transfer.comment ?? ''}`
    return label.toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru'))
  })
  const pageCount = type === 'transaction' && list.data && !Array.isArray(list.data) ? Math.max(1, Math.ceil((list.data.total ?? 0) / pageSize)) : 1
  const invalidate = async (includeTransfers = false) => {
    await Promise.all([
      client.invalidateQueries({ queryKey: [config.endpoint] }),
      client.invalidateQueries({ queryKey: [config.endpoint.slice(1)] }),
      client.invalidateQueries({ queryKey: ['accounts'] }),
      client.invalidateQueries({ queryKey: ['forecast'] }),
      client.invalidateQueries({ queryKey: ['analytics'] }),
      ...(includeTransfers ? [client.invalidateQueries({ queryKey: ['/transfers'] })] : []),
    ])
  }
  const save = useMutation<unknown, Error, ResourceSubmission>({ mutationFn: ({ values, idempotencyKey, item }) => {
    if (item) {
      if ('from_account_id' in item) return api(`/transfers/${item.id}`, { method: 'PATCH', body: jsonBody({ from_account_id: Number(values.account_id), to_account_id: Number(values.to_account_id), amount_minor: parseMoney(values.amount!), date: values.date, comment: values.comment?.trim() || null, version: itemVersion(item) }) })
      if (type === 'loan') return api(`/loans/${item.id}`, { method: 'PATCH', body: jsonBody({ name: values.title!.trim(), creditor: values.creditor?.trim() || null, principal_minor: values.amount?.trim() ? parseMoney(values.amount) : null, principal_as_of: values.principal_as_of || null, account_id: values.account_id ? Number(values.account_id) : null, start_date: values.start_date || null, end_date: values.end_date || null, comment: values.comment?.trim() || null, version: itemVersion(item) }) })
      if (type === 'transaction') return api(`/transactions/${item.id}`, { method: 'PATCH', body: jsonBody({ amount_minor: parseMoney(values.amount!), date: values.date, category_id: values.category_id ? Number(values.category_id) : null, description: values.title!.trim(), comment: values.comment?.trim() || null, tag_ids: numericIds(values.tag_ids), version: itemVersion(item) }) })
      return api(`/plan-items/${item.id}`, { method: 'PATCH', body: jsonBody({ title: values.title!.trim(), amount_minor: parseMoney(values.amount!), end_date: values.end_date || null, certainty: values.certainty || 'confirmed', account_id: values.account_id ? Number(values.account_id) : null, category_id: values.category_id ? Number(values.category_id) : null, tag_ids: numericIds(values.tag_ids), comment: values.comment?.trim() || null, version: itemVersion(item) }) })
    }
    if (type === 'loan') return api(config.endpoint, { method: 'POST', body: jsonBody({ name: values.title!.trim(), creditor: values.creditor?.trim() || null, principal_minor: values.amount?.trim() ? parseMoney(values.amount) : null, principal_as_of: values.principal_as_of || null, account_id: values.account_id ? Number(values.account_id) : null, start_date: values.start_date || null, end_date: values.end_date || null, comment: values.comment?.trim() || null }) })
    if (type === 'transaction' && values.transaction_type === 'transfer') return api('/transfers', { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: jsonBody({ from_account_id: Number(values.account_id), to_account_id: Number(values.to_account_id), amount_minor: parseMoney(values.amount!), date: values.date, comment: values.comment || null }) })
    if (type === 'transaction') return api(config.endpoint, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: jsonBody({ type: values.transaction_type || 'expense', amount_minor: parseMoney(values.amount!), date: values.date, account_id: Number(values.account_id), category_id: values.category_id ? Number(values.category_id) : null, description: values.title!.trim(), comment: values.comment || null, tag_ids: numericIds(values.tag_ids) }) })
    const recurrence = values.recurrence || 'none'
    return api(config.endpoint, { method: 'POST', body: jsonBody({ kind: type === 'income' ? 'income' : 'expense', title: values.title!.trim(), amount_minor: parseMoney(values.amount!), date: values.date || null, month: values.date ? null : values.month, recurrence, start_date: recurrence === 'none' ? null : values.date, end_date: values.end_date || null, certainty: values.certainty || 'confirmed', account_id: values.account_id ? Number(values.account_id) : null, category_id: values.category_id ? Number(values.category_id) : null, funding_source: 'free', tag_ids: numericIds(values.tag_ids), comment: values.comment?.trim() || null }) })
  }, onSuccess: async (_result, { values, item }) => {
    await invalidate(values.transaction_type === 'transfer' || Boolean(item && 'from_account_id' in item))
    if (values.transaction_type === 'transfer') {
      setTransferSaved(!item)
    }
    setOpen(false)
    setEditing(null)
  } })
  const changeState = useMutation<unknown, Error, { item: Item; patch: Record<string, unknown> }>({
    mutationFn: ({ item, patch }) => api(`${config.endpoint}/${item.id}`, { method: 'PATCH', body: jsonBody({ ...patch, version: itemVersion(item) }) }),
    onSuccess: () => invalidate(),
  })
  const remove = useMutation<unknown, Error, { endpoint: string; item: { id: ID; version?: number } }>({
    mutationFn: ({ endpoint, item }) => api(`${endpoint}/${item.id}?${queryString({ version: itemVersion(item) })}`, { method: 'DELETE' }),
    onSuccess: (_result, { endpoint }) => invalidate(endpoint === '/transfers'),
  })
  const editItem = (item: EditableItem) => { save.reset(); changeState.reset(); remove.reset(); setTransferSaved(false); setOpen(false); setEditing(item) }
  const deleteItem = (endpoint: string, item: EditableItem, label: string) => {
    remove.reset()
    if (window.confirm(`Удалить «${label}» безвозвратно? Если запись связана с историей, сервер не позволит удаление.`)) remove.mutate({ endpoint, item })
  }
  const mutationError = actionError(changeState.error ?? remove.error)
  return <div className="page"><PageHeader eyebrow={config.eyebrow} title={config.title} description={config.description} actions={<Button onClick={() => { save.reset(); changeState.reset(); remove.reset(); setEditing(null); setTransferSaved(false); setOpen(true) }}><CirclePlus/> {config.add}</Button>} />
    <div className="list-toolbar"><label className="search"><Search/><input placeholder="Поиск" value={search} onChange={(e) => setSearch(e.target.value)}/></label>{type === 'transaction' && <Badge tone="neutral">Переводы не входят в доходы и расходы</Badge>}</div>
    {transferSaved && <div className="notice notice--calm"><ArrowRight/><div><strong>Перевод сохранён</strong><span>Деньги перемещены между счетами без изменения общих доходов и расходов.</span></div></div>}
    {mutationError && <div className="form-alert" role="alert">{mutationError}</div>}
    {list.isLoading && <State kind="loading" title="Загружаем данные"/>}{list.isError && <ErrorState error={list.error} retry={() => list.refetch()}/>} 
    {!list.isLoading && !list.isError && (items.length ? <div className="data-card">
      <div className="data-list data-list--header"><span>Название</span><span>Дата</span><span>Статус / тип</span><span>Сумма</span><span/></div>
      {items.map((item) => <div className="data-list" key={item.id}>
        <div><strong>{resourceName(item)}</strong><small>{'recurrence' in item && item.recurrence !== 'none' ? `Повтор: ${item.recurrence === 'monthly' ? 'ежемесячно' : 'ежегодно'}` : type === 'loan' && 'creditor' in item && item.creditor ? item.creditor : 'Разовая запись'}</small></div>
        <span>{dateLabel(resourceDate(item))}</span>
        <span>{type === 'loan' && 'archived' in item && item.archived ? statusBadge('archived') : 'status' in item ? statusBadge(item.status) : 'type' in item ? statusBadge(item.type) : statusBadge(item.status)}</span>
        <strong className={(('kind' in item && item.kind === 'income') || ('type' in item && item.type === 'income')) ? 'positive' : ''}>{formatMoney(resourceAmount(item))}</strong>
        <div className="row-actions">
          {type === 'loan' && !(item as Loan).archived && <button className="icon-button" aria-label={`График кредита ${resourceName(item)}`} title="График" onClick={() => setScheduleLoan(item as Loan)}><CalendarPlus/></button>}
          {(type === 'income' || type === 'payment') && <button className="icon-button" aria-label={`Сверить с фактом ${resourceName(item)}`} title="Сверить" onClick={() => setMatchingPlan(item as PlanItem)}><ArrowRight/></button>}
          <button className="icon-button" aria-label={`Изменить ${resourceName(item)}`} title="Изменить" onClick={() => editItem(item)}><Pencil/></button>
          {type === 'loan' && <button className="icon-button" aria-label={`${(item as Loan).archived ? 'Восстановить' : 'Архивировать'} ${resourceName(item)}`} title={(item as Loan).archived ? 'Восстановить' : 'Архивировать'} onClick={() => {
            const loan = item as Loan; changeState.reset()
            if (loan.archived || window.confirm(`Архивировать «${resourceName(item)}»? График и история платежей сохранятся.`)) changeState.mutate({ item, patch: { archived: !loan.archived } })
          }}>{(item as Loan).archived ? <RotateCcw/> : <Archive/>}</button>}
          {(type === 'income' || type === 'payment') && <button className="icon-button" aria-label={`${(item as PlanItem).status === 'cancelled' ? 'Восстановить' : 'Отменить'} ${resourceName(item)}`} title={(item as PlanItem).status === 'cancelled' ? 'Восстановить' : 'Отменить'} onClick={() => {
            const plan = item as PlanItem; changeState.reset()
            if (plan.status === 'cancelled' || window.confirm(`Отменить «${resourceName(item)}»? Запись останется в истории.`)) changeState.mutate({ item, patch: { status: plan.status === 'cancelled' ? 'planned' : 'cancelled' } })
          }}>{(item as PlanItem).status === 'cancelled' ? <RotateCcw/> : <Ban/>}</button>}
          <button className="icon-button icon-button--danger" aria-label={`Удалить ${resourceName(item)}`} title="Удалить" onClick={() => deleteItem(config.endpoint, item, resourceName(item))}><Trash2/></button>
        </div>
      </div>)}
    </div> : <State title={config.empty}>{type === 'transaction' ? 'Внесите первую операцию вручную или импортируйте CSV.' : `Нажмите «${config.add}», чтобы начать.`}</State>)}
    {pageCount > 1 && <div className="pagination"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Назад</Button><span>Страница {page} из {pageCount}</span><Button variant="secondary" disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)}>Далее</Button></div>}
    {type === 'transaction' && <section style={{ marginTop: 24 }}>
      <div className="section-head"><div><span className="eyebrow">Между своими счетами</span><h2>Переводы</h2></div></div>
      {transfers.isLoading && <State kind="loading" title="Загружаем переводы" />}
      {transfers.isError && <ErrorState error={transfers.error} retry={() => transfers.refetch()} />}
      {!transfers.isLoading && !transfers.isError && (transferItems.length ? <div className="data-card">
        <div className="data-list data-list--header"><span>Направление</span><span>Дата</span><span>Тип</span><span>Сумма</span><span /></div>
        {transferItems.map((transfer) => <div className="data-list" key={transfer.id}>
          <div><strong>{accountNames.get(String(transfer.from_account_id)) ?? `Счёт ${transfer.from_account_id}`} → {accountNames.get(String(transfer.to_account_id)) ?? `Счёт ${transfer.to_account_id}`}</strong><small>{transfer.comment || 'Внутреннее перемещение'}</small></div>
          <span>{dateLabel(transfer.date)}</span><span><Badge tone="neutral">Перевод</Badge></span><strong>{formatMoney(transfer.amount_minor)}</strong><div className="row-actions"><button className="icon-button" aria-label={`Изменить перевод ${transfer.id}`} title="Изменить" onClick={() => editItem(transfer)}><Pencil/></button><button className="icon-button icon-button--danger" aria-label={`Удалить перевод ${transfer.id}`} title="Удалить" onClick={() => deleteItem('/transfers', transfer, `перевод от ${dateLabel(transfer.date)}`)}><Trash2/></button></div>
        </div>)}
      </div> : <State title={asList(transfers.data).length ? 'Переводы не найдены' : 'Переводов пока нет'}>{asList(transfers.data).length ? 'Измените строку поиска.' : 'Создайте перевод через кнопку «Добавить операцию».'}</State>)}
    </section>}
    {(open || editing) && <ResourceForm type={type} item={editing ?? undefined} accounts={asList(accounts.data)} categories={asList(categories.data)} tags={asList(tags.data)} mutation={save} onClose={() => { setOpen(false); setEditing(null) }}/>} 
    {matchingPlan && <PlanMatchForm plan={matchingPlan} onClose={() => setMatchingPlan(null)} />}
    {scheduleLoan && <LoanSchedule loan={scheduleLoan} accounts={asList(accounts.data)} categories={asList(categories.data)} onClose={() => setScheduleLoan(null)}/>} 
  </div>
}

function resourceDefaults(type: ResourceType, item?: EditableItem): FormValues {
  if (!item) return { certainty: 'confirmed', recurrence: 'none', transaction_type: 'expense', tag_ids: [] }
  if ('from_account_id' in item) return {
    transaction_type: 'transfer', amount: moneyInput(item.amount_minor), date: item.date,
    account_id: String(item.from_account_id), to_account_id: String(item.to_account_id), comment: item.comment ?? '', tag_ids: [],
  }
  if (type === 'loan') {
    const loan = item as Loan
    return { title: loan.name, creditor: loan.creditor ?? '', amount: loan.principal_minor == null ? '' : moneyInput(loan.principal_minor), principal_as_of: loan.principal_as_of ?? '', account_id: loan.account_id == null ? '' : String(loan.account_id), start_date: loan.start_date ?? '', end_date: loan.end_date ?? '', comment: loan.comment ?? '', tag_ids: [] }
  }
  if (type === 'transaction') {
    const transaction = item as Transaction
    return { title: transaction.description ?? '', amount: moneyInput(transaction.amount_minor), date: transaction.date, account_id: transaction.account_id == null ? '' : String(transaction.account_id), category_id: transaction.category_id == null ? '' : String(transaction.category_id), transaction_type: transaction.type, comment: transaction.comment ?? '', tag_ids: transaction.tags?.map((tag) => String(tag.id)) ?? [] }
  }
  const plan = item as PlanItem
  return { title: plan.title, amount: moneyInput(plan.amount_minor), date: plan.date ?? plan.start_date ?? '', month: plan.month ?? '', account_id: plan.account_id == null ? '' : String(plan.account_id), category_id: plan.category_id == null ? '' : String(plan.category_id), recurrence: plan.recurrence, certainty: plan.certainty, end_date: plan.end_date ?? '', comment: plan.comment ?? '', tag_ids: plan.tags?.map((tag) => String(tag.id)) ?? [] }
}

function ResourceForm({ type, item, accounts, categories, tags, mutation, onClose }: { type: ResourceType; item?: EditableItem; accounts: Account[]; categories: Category[]; tags: Tag[]; mutation: ReturnType<typeof useMutation<unknown, Error, ResourceSubmission>>; onClose: () => void }) {
  const submissionKey = useRef<string | null>(null)
  const { register, handleSubmit, watch, formState: { errors, isDirty } } = useForm<FormValues>({ resolver: zodResolver(schemaFor(type)), defaultValues: resourceDefaults(type, item) })
  const transactionType = watch('transaction_type')
  const accountId = watch('account_id')
  const recurrence = watch('recurrence')
  const isTransfer = type === 'transaction' && transactionType === 'transfer'
  const isEditing = Boolean(item)
  const currentAccountIds = new Set<string>()
  if (item && 'from_account_id' in item) {
    currentAccountIds.add(String(item.from_account_id))
    currentAccountIds.add(String(item.to_account_id))
  } else if (item && 'account_id' in item && item.account_id != null) {
    currentAccountIds.add(String(item.account_id))
  }
  const currentCategoryId = item && !('from_account_id' in item) && 'category_id' in item && item.category_id != null
    ? String(item.category_id)
    : undefined
  const currentTagIds = new Set(
    item && !('from_account_id' in item) && 'tags' in item
      ? (item.tags ?? []).map((tag) => String(tag.id))
      : [],
  )
  const availableAccounts = accounts.filter((account) => !account.archived || currentAccountIds.has(String(account.id)))
  const availableCategories = categories.filter((category) => !category.archived || String(category.id) === currentCategoryId)
  const availableTags = tags.filter((tag) => !tag.archived || currentTagIds.has(String(tag.id)))
  const optionLabel = (name: string, archived?: boolean) => archived ? `${name} (в архиве)` : name
  const close = () => (!isDirty || window.confirm('Закрыть форму и потерять несохранённые изменения?')) && onClose()
  const submit = (values: FormValues) => {
    const idempotencyKey = submissionKey.current ?? newIdempotencyKey(type === 'transaction' ? 'transaction' : type)
    submissionKey.current = idempotencyKey
    mutation.mutate({ values, idempotencyKey, item }, { onSettled: () => { submissionKey.current = null } })
  }
  const modalTitle = isEditing ? isTransfer ? 'Изменить перевод' : `Изменить «${item && !('from_account_id' in item) ? resourceName(item) : ''}»` : isTransfer ? 'Внутренний перевод' : configs[type].add
  return <Modal title={modalTitle} onClose={close}><form className="form-grid" onSubmit={handleSubmit(submit)}>
    {type === 'transaction' && <Field label="Тип операции" hint={isEditing ? 'Тип сохранённой операции нельзя изменить' : undefined}>{isEditing ? <div className="field-control"><Select value={transactionType} disabled><option value="expense">Расход</option><option value="income">Доход</option><option value="refund">Возврат расхода</option><option value="adjustment">Корректировка остатка</option><option value="transfer">Перевод между счетами</option></Select><input type="hidden" {...register('transaction_type')} /></div> : <Select {...register('transaction_type')} autoFocus><option value="expense">Расход</option><option value="income">Доход</option><option value="refund">Возврат расхода</option><option value="adjustment">Корректировка остатка</option><option value="transfer">Перевод между счетами</option></Select>}</Field>}
    {!isTransfer && <Field label="Название" error={errors.title?.message}><Input {...register('title')} autoFocus={type !== 'transaction'} placeholder={type === 'income' ? 'Например, зарплата' : type === 'loan' ? 'Например, ипотека' : 'Например, аренда'} /></Field>}
    {type === 'loan' && <Field label="Кредитор"><Input {...register('creditor')} /></Field>}
    <Field label={type === 'loan' ? 'Известный основной долг' : 'Сумма'} error={errors.amount?.message}><Input inputMode="decimal" {...register('amount')} placeholder="0,00" /></Field>
    {type !== 'loan' && <Field label="Дата" error={errors.date?.message} hint={isEditing && !isTransfer && type !== 'transaction' ? 'Дата и периодичность плана фиксируются при создании' : undefined}><Input type="date" {...register('date')} readOnly={isEditing && !isTransfer && type !== 'transaction'} /></Field>}
    {(type === 'income' || type === 'payment') && <><Field label="Только месяц" hint="Используйте, если точный день неизвестен"><Input type="month" {...register('month')} readOnly={isEditing} /></Field><Field label="Повторение">{isEditing ? <div className="field-control"><Select value={recurrence} disabled><option value="none">Не повторять</option><option value="monthly">Каждый месяц</option><option value="yearly">Каждый год</option></Select><input type="hidden" {...register('recurrence')} /></div> : <Select {...register('recurrence')}><option value="none">Не повторять</option><option value="monthly">Каждый месяц</option><option value="yearly">Каждый год</option></Select>}</Field><Field label="Дата окончания" hint="Необязательно, для повторяющихся планов"><Input type="date" {...register('end_date')} /></Field></>}
    {type === 'income' && <Field label="Определённость"><Select {...register('certainty')}><option value="confirmed">Подтверждён</option><option value="possible">Возможен</option></Select></Field>}
    {type === 'loan' && <><Field label="Остаток долга на дату"><Input type="date" {...register('principal_as_of')} /></Field><Field label="Счёт списания"><Select {...register('account_id')}><option value="">Не выбран</option>{availableAccounts.map((account) => <option key={account.id} value={account.id}>{optionLabel(account.name, account.archived)}</option>)}</Select></Field><Field label="Дата начала"><Input type="date" {...register('start_date')} /></Field><Field label="Дата окончания"><Input type="date" {...register('end_date')} /></Field></>}
    {type !== 'loan' && <Field label={isTransfer ? 'Со счёта' : 'Счёт'} error={errors.account_id?.message} hint={isEditing && type === 'transaction' && !isTransfer ? 'Счёт сохранённой операции нельзя изменить' : undefined}>{isEditing && type === 'transaction' && !isTransfer ? <div className="field-control"><Select value={accountId} disabled><option value="">Не выбран</option>{availableAccounts.map((account) => <option key={account.id} value={account.id}>{optionLabel(account.name, account.archived)}</option>)}</Select><input type="hidden" {...register('account_id')} /></div> : <Select {...register('account_id')}><option value="">Не выбран</option>{availableAccounts.map((account) => <option key={account.id} value={account.id}>{optionLabel(account.name, account.archived)}</option>)}</Select>}</Field>}
    {isTransfer && <Field label="На счёт" error={errors.to_account_id?.message}><Select {...register('to_account_id')}><option value="">Не выбран</option>{availableAccounts.map((account) => <option key={account.id} value={account.id}>{optionLabel(account.name, account.archived)}</option>)}</Select></Field>}
    {type !== 'loan' && !isTransfer && <Field label="Категория"><Select {...register('category_id')}><option value="">Без категории</option>{availableCategories.map((category) => <option key={category.id} value={category.id}>{optionLabel(category.name, category.archived)}</option>)}</Select></Field>}
    {type !== 'loan' && !isTransfer && <Field label="Теги" hint="Можно выбрать несколько с Ctrl или Cmd"><Select multiple size={Math.min(4, Math.max(2, availableTags.length))} {...register('tag_ids')}>{availableTags.map((tag) => <option key={tag.id} value={tag.id}>{optionLabel(tag.name, tag.archived)}</option>)}</Select></Field>}
    {isTransfer && <p className="form-hint form-span">Перевод создаётся одной атомарной операцией и не попадёт в общие доходы или расходы.</p>}
    <Field label="Комментарий" error={errors.comment?.message}><textarea className="input textarea" {...register('comment')} /></Field>
    {mutation.isError && <div className="form-alert form-span" role="alert">{actionError(mutation.error)}</div>}<div className="form-actions form-span"><Button type="button" variant="ghost" onClick={close}>Отмена</Button><Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? 'Сохраняем…' : isEditing ? 'Сохранить изменения' : isTransfer ? 'Перевести' : 'Сохранить'}</Button></div>
  </form></Modal>
}

const matchSchema = z.object({
  transaction_id: z.string().min(1, 'Выберите операцию'),
  occurrence_month: z.string().regex(/^\d{4}-(0[1-9]|1[0-2])$/, 'Укажите месяц плана'),
  amount: z.string().min(1, 'Укажите сумму'),
  completed: z.boolean().default(false),
}).superRefine((values, context) => {
  try {
    if (parseMoney(values.amount) <= 0) throw new Error()
  } catch {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['amount'], message: 'Укажите сумму больше нуля' })
  }
})
type MatchValues = z.infer<typeof matchSchema>
interface MatchSubmission { values: MatchValues; idempotencyKey: string }

function planOccurrenceMonth(plan: PlanItem) {
  if (plan.recurrence !== 'none') return localDate().slice(0, 7)
  return plan.month ?? plan.date?.slice(0, 7) ?? plan.start_date?.slice(0, 7) ?? localDate().slice(0, 7)
}

function PlanMatchForm({ plan, onClose }: { plan: PlanItem; onClose: () => void }) {
  const client = useQueryClient()
  const submissionKey = useRef<string | null>(null)
  const transactions = useQuery<Transaction[] | ListResponse<Transaction>>({
    queryKey: ['/transactions', 'unmatched', plan.kind],
    queryFn: () => api('/transactions?limit=500&offset=0'),
  })
  const facts = asList(transactions.data).filter((transaction) => transaction.type === plan.kind
    && transaction.matched_plan_item_id == null
    && !transaction.external_source?.startsWith('loan_schedule:'))
  const { register, handleSubmit, setValue, formState: { errors, isDirty } } = useForm<MatchValues>({
    resolver: zodResolver(matchSchema),
    defaultValues: { transaction_id: '', occurrence_month: planOccurrenceMonth(plan), amount: '', completed: false },
  })
  const match = useMutation<unknown, Error, MatchSubmission>({
    mutationFn: ({ values, idempotencyKey }) => api(`/plan-items/${plan.id}/matches`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: jsonBody({
        transaction_id: Number(values.transaction_id),
        occurrence_month: values.occurrence_month,
        amount_minor: parseMoney(values.amount),
        completed: values.completed,
      }),
    }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['/transactions'] }),
        client.invalidateQueries({ queryKey: ['/plan-items'] }),
        client.invalidateQueries({ queryKey: ['forecast'] }),
      ])
      onClose()
    },
  })
  const transactionRegistration = register('transaction_id')
  const submit = (values: MatchValues) => {
    const idempotencyKey = submissionKey.current ?? newIdempotencyKey('plan-match')
    submissionKey.current = idempotencyKey
    match.mutate({ values, idempotencyKey }, { onSettled: () => { submissionKey.current = null } })
  }
  const close = () => (!isDirty || window.confirm('Закрыть сверку и потерять введённые данные?')) && onClose()

  return <Modal title={`Сверить «${plan.title}» с фактом`} onClose={close}>
    {transactions.isLoading && <State kind="loading" title="Ищем несверенные операции" />}
    {transactions.isError && <ErrorState error={transactions.error} retry={() => transactions.refetch()} />}
    {!transactions.isLoading && !transactions.isError && (facts.length ? <form className="form-grid" onSubmit={handleSubmit(submit)}>
      <Field label="Несверенная операция" error={errors.transaction_id?.message}><Select {...transactionRegistration} onChange={(event) => {
        transactionRegistration.onChange(event)
        const fact = facts.find((item) => String(item.id) === event.target.value)
        if (fact) {
          setValue('amount', moneyInput(Math.min(plan.amount_minor, fact.amount_minor)), { shouldDirty: true, shouldValidate: true })
          if (plan.recurrence !== 'none') setValue('occurrence_month', fact.date.slice(0, 7), { shouldDirty: true, shouldValidate: true })
        }
      }} autoFocus><option value="">Выберите факт</option>{facts.map((fact) => <option key={fact.id} value={fact.id}>{dateLabel(fact.date)} · {fact.description || 'Операция'} · {formatMoney(fact.amount_minor)}</option>)}</Select></Field>
      <Field label="Месяц плана" error={errors.occurrence_month?.message}><Input type="month" {...register('occurrence_month')} /></Field>
      <Field label="Сумма сверки" error={errors.amount?.message}><Input inputMode="decimal" placeholder="0,00" {...register('amount')} /></Field>
      <label className="import-confirm-option form-span"><input type="checkbox" aria-label="План исполнен полностью" {...register('completed')} /><span><strong>План исполнен полностью</strong><small>Остаток ожидания станет нулевым, даже если сумма факта отличается.</small></span></label>
      {match.isError && <div className="form-alert form-span">{match.error.message}</div>}
      <div className="form-actions form-span"><Button type="button" variant="ghost" onClick={close}>Отмена</Button><Button type="submit" disabled={match.isPending}>{match.isPending ? 'Сверяем…' : 'Сверить'}</Button></div>
    </form> : <State title="Нет несверенных операций">Добавьте или импортируйте факт того же типа, затем вернитесь к сверке.</State>)}
  </Modal>
}

const scheduleSchema = z.object({
  due_date: z.string().min(1, 'Укажите дату платежа'),
  amount: z.string().min(1, 'Укажите сумму платежа'),
  principal: z.string().optional(),
  interest: z.string().optional(),
}).superRefine((values, context) => {
  let amount: number | undefined
  try {
    amount = parseMoney(values.amount)
    if (amount <= 0) throw new Error()
  } catch {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['amount'], message: 'Укажите сумму больше нуля' })
  }
  const parts = (['principal', 'interest'] as const).map((field) => {
    if (!values[field]?.trim()) return 0
    try {
      const value = parseMoney(values[field]!)
      if (value < 0) throw new Error()
      return value
    } catch {
      context.addIssue({ code: z.ZodIssueCode.custom, path: [field], message: 'Укажите неотрицательную сумму' })
      return 0
    }
  })
  if (amount !== undefined && parts[0] + parts[1] > amount) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['amount'], message: 'Основной долг и проценты не могут быть больше платежа' })
  }
})
type ScheduleValues = z.infer<typeof scheduleSchema>

function optionalMoney(value?: string) { return value?.trim() ? parseMoney(value) : null }

const loanPaymentSchema = z.object({
  date: z.string().min(1, 'Укажите дату платежа'),
  amount: z.string().min(1, 'Укажите сумму платежа'),
  principal: z.string().optional(),
  interest: z.string().optional(),
  account_id: z.string().min(1, 'Выберите счёт'),
  category_id: z.string().optional(),
  completed: z.boolean().default(false),
  comment: z.string().optional(),
}).superRefine((values, context) => {
  let amount: number | undefined
  try {
    amount = parseMoney(values.amount)
    if (amount <= 0) throw new Error()
  } catch {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['amount'], message: 'Укажите сумму больше нуля' })
  }
  const parts = (['principal', 'interest'] as const).map((field) => {
    if (!values[field]?.trim()) return 0
    try {
      const value = parseMoney(values[field]!)
      if (value < 0) throw new Error()
      return value
    } catch {
      context.addIssue({ code: z.ZodIssueCode.custom, path: [field], message: 'Укажите неотрицательную сумму' })
      return 0
    }
  })
  if (amount !== undefined && parts[0] + parts[1] > amount) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['amount'], message: 'Основной долг и проценты не могут быть больше платежа' })
  }
})
type LoanPaymentValues = z.infer<typeof loanPaymentSchema>
interface LoanPaymentSubmission { values: LoanPaymentValues; idempotencyKey: string }

function LoanPaymentForm({ loan, item, accounts, categories, onCancel, onPaid }: { loan: Loan; item: LoanScheduleItem; accounts: Account[]; categories: Category[]; onCancel: () => void; onPaid: () => void }) {
  const client = useQueryClient()
  const submissionKey = useRef<string | null>(null)
  const remaining = item.remaining_minor ?? Math.max(0, item.amount_minor - item.paid_minor)
  const { register, handleSubmit, formState: { errors } } = useForm<LoanPaymentValues>({
    resolver: zodResolver(loanPaymentSchema),
    defaultValues: {
      date: localDate(), amount: moneyInput(remaining), principal: '', interest: '',
      account_id: loan.account_id == null ? '' : String(loan.account_id), category_id: '', completed: false, comment: '',
    },
  })
  const payment = useMutation<unknown, Error, LoanPaymentSubmission>({
    mutationFn: ({ values, idempotencyKey }) => api(`/loans/${loan.id}/schedule/${item.id}/payments`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: jsonBody({
        amount_minor: parseMoney(values.amount),
        principal_minor: optionalMoney(values.principal),
        interest_minor: optionalMoney(values.interest),
        date: values.date,
        account_id: Number(values.account_id),
        category_id: values.category_id ? Number(values.category_id) : null,
        completed: values.completed,
        comment: values.comment?.trim() || null,
      }),
    }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['/loans', loan.id, 'schedule'] }),
        client.invalidateQueries({ queryKey: ['/loans'] }),
        client.invalidateQueries({ queryKey: ['/transactions'] }),
        client.invalidateQueries({ queryKey: ['accounts'] }),
        client.invalidateQueries({ queryKey: ['forecast'] }),
      ])
      onPaid()
    },
  })
  const submit = (values: LoanPaymentValues) => {
    const idempotencyKey = submissionKey.current ?? newIdempotencyKey('loan-payment')
    submissionKey.current = idempotencyKey
    payment.mutate({ values, idempotencyKey }, { onSettled: () => { submissionKey.current = null } })
  }
  const activeAccounts = accounts.filter((account) => !account.archived || String(account.id) === String(loan.account_id))
  const expenseCategories = categories.filter((category) => {
    const kind = category.kind ?? category.type
    return !category.archived && (!kind || kind === 'expense')
  })

  return <form className="schedule-form form-grid" onSubmit={handleSubmit(submit)}>
    <p className="form-hint form-span">Платёж по строке от {dateLabel(item.due_date)} · осталось {formatMoney(remaining)}. Укажите фактически списанную сумму.</p>
    <Field label="Дата списания" error={errors.date?.message}><Input type="date" {...register('date')} autoFocus /></Field>
    <Field label="Фактическая сумма" error={errors.amount?.message}><Input inputMode="decimal" {...register('amount')} /></Field>
    <Field label="В составе основной долг" error={errors.principal?.message}><Input inputMode="decimal" placeholder="Необязательно" {...register('principal')} /></Field>
    <Field label="В составе проценты" error={errors.interest?.message}><Input inputMode="decimal" placeholder="Необязательно" {...register('interest')} /></Field>
    <Field label="Счёт списания" error={errors.account_id?.message}><Select {...register('account_id')}><option value="">Не выбран</option>{activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</Select></Field>
    <Field label="Категория"><Select {...register('category_id')}><option value="">Без категории</option>{expenseCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</Select></Field>
    <label className="import-confirm-option form-span"><input type="checkbox" aria-label="Закрыть строку полностью" {...register('completed')} /><span><strong>Закрыть строку полностью</strong><small>Используйте, если банк считает обязательство исполненным даже при сумме меньше плановой.</small></span></label>
    <Field label="Комментарий"><textarea className="input textarea" {...register('comment')} /></Field>
    {payment.isError && <div className="form-alert form-span" role="alert">{actionError(payment.error)}</div>}
    <div className="form-actions form-span"><Button type="button" variant="ghost" onClick={onCancel}>Отмена</Button><Button type="submit" disabled={payment.isPending}>{payment.isPending ? 'Проводим…' : 'Провести платёж'}</Button></div>
  </form>
}

function LoanSchedule({ loan, accounts, categories, onClose }: { loan: Loan; accounts: Account[]; categories: Category[]; onClose: () => void }) {
  const client = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [editingItem, setEditingItem] = useState<LoanScheduleItem | null>(null)
  const [payingItem, setPayingItem] = useState<LoanScheduleItem | null>(null)
  const schedule = useQuery<LoanScheduleItem[] | ListResponse<LoanScheduleItem>>({
    queryKey: ['/loans', loan.id, 'schedule'],
    queryFn: () => api(`/loans/${loan.id}/schedule`),
  })
  const { register, handleSubmit, reset, formState: { errors, isDirty } } = useForm<ScheduleValues>({
    resolver: zodResolver(scheduleSchema),
    defaultValues: { due_date: '', amount: '', principal: '', interest: '' },
  })
  const invalidate = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['/loans', loan.id, 'schedule'] }),
      client.invalidateQueries({ queryKey: ['/loans'] }),
      client.invalidateQueries({ queryKey: ['forecast'] }),
    ])
  }
  const save = useMutation<unknown,Error,{values:ScheduleValues;item?:LoanScheduleItem}>({
    mutationFn: ({values,item}) => api(item ? `/loans/${loan.id}/schedule/${item.id}` : `/loans/${loan.id}/schedule`, {
      method: item ? 'PATCH' : 'POST',
      body: jsonBody({
        due_date: values.due_date,
        amount_minor: parseMoney(values.amount),
        principal_minor: optionalMoney(values.principal),
        interest_minor: optionalMoney(values.interest),
        ...(item ? {version:itemVersion(item)} : {}),
      }),
    }),
    onSuccess: async () => {
      await invalidate()
      reset()
      setAdding(false)
      setEditingItem(null)
    },
  })
  const state = useMutation<unknown,Error,{item:LoanScheduleItem;status:'planned'|'cancelled'}>({
    mutationFn:({item,status})=>api(`/loans/${loan.id}/schedule/${item.id}`,{method:'PATCH',body:jsonBody({status,version:itemVersion(item)})}),
    onSuccess:invalidate,
  })
  const remove = useMutation<unknown,Error,LoanScheduleItem>({
    mutationFn:(item)=>api(`/loans/${loan.id}/schedule/${item.id}?${queryString({version:itemVersion(item)})}`,{method:'DELETE'}),
    onSuccess:invalidate,
  })
  const items = asList(schedule.data)
  const remaining = items.reduce((sum, item) => sum + (item.status === 'cancelled' ? 0 : Math.max(0, item.amount_minor - item.paid_minor)), 0)
  const hasUnsaved = ((adding || Boolean(editingItem)) && isDirty) || Boolean(payingItem)
  const close = () => (!hasUnsaved || window.confirm('Закрыть график и потерять несохранённые данные?')) && onClose()
  const resetActions = () => { save.reset(); state.reset(); remove.reset() }
  const openNew = () => { resetActions(); reset({due_date:'',amount:'',principal:'',interest:''}); setEditingItem(null); setPayingItem(null); setAdding(true) }
  const openEdit = (item:LoanScheduleItem) => { resetActions(); reset({due_date:item.due_date,amount:moneyInput(item.amount_minor),principal:item.principal_minor==null?'':moneyInput(item.principal_minor),interest:item.interest_minor==null?'':moneyInput(item.interest_minor)}); setAdding(false); setPayingItem(null); setEditingItem(item) }
  const mutationError=actionError(save.error??state.error??remove.error)

  return <Modal title={`График кредита «${loan.name}»`} onClose={close}>
    <div className="schedule-summary"><div><span>Строк в графике</span><strong>{items.length}</strong></div><div><span>Остаток платежей</span><strong>{formatMoney(remaining)}</strong></div><Button variant="secondary" onClick={openNew} disabled={adding || Boolean(editingItem) || Boolean(payingItem)}><CirclePlus/> Добавить строку</Button></div>
    {(adding||editingItem) && <form className="schedule-form form-grid" onSubmit={handleSubmit((values) => save.mutate({values,item:editingItem??undefined}))}>
      {editingItem&&<p className="form-hint form-span">Изменяется строка от {dateLabel(editingItem.due_date)}. Строки с проведёнными платежами защищены от независимого изменения.</p>}
      <Field label="Дата платежа" error={errors.due_date?.message}><Input type="date" {...register('due_date')} autoFocus /></Field>
      <Field label="Сумма платежа" error={errors.amount?.message}><Input inputMode="decimal" {...register('amount')} placeholder="0,00" /></Field>
      <Field label="В составе основной долг" error={errors.principal?.message}><Input inputMode="decimal" {...register('principal')} placeholder="Необязательно" /></Field>
      <Field label="В составе проценты" error={errors.interest?.message}><Input inputMode="decimal" {...register('interest')} placeholder="Необязательно" /></Field>
      {save.isError && <div className="form-alert form-span" role="alert">{actionError(save.error)}</div>}
      <div className="form-actions form-span"><Button type="button" variant="ghost" onClick={() => { reset(); setAdding(false); setEditingItem(null) }}>Отмена</Button><Button type="submit" disabled={save.isPending}>{save.isPending ? 'Сохраняем…' : editingItem?'Сохранить изменения':'Сохранить строку'}</Button></div>
    </form>}
    {payingItem && <LoanPaymentForm key={payingItem.id} loan={loan} item={payingItem} accounts={accounts} categories={categories} onCancel={() => setPayingItem(null)} onPaid={() => setPayingItem(null)} />}
    {mutationError&&!save.isError&&<div className="form-alert" role="alert">{mutationError}</div>}
    {schedule.isLoading && <State kind="loading" title="Загружаем график" />}
    {schedule.isError && <ErrorState error={schedule.error} retry={() => schedule.refetch()} />}
    {!schedule.isLoading && !schedule.isError && (items.length ? <div className="schedule-list">
      <div className="schedule-row schedule-row--header"><span>Дата</span><span>Платёж</span><span>Оплачено</span><span>Статус / действие</span></div>
      {items.map((item) => {
        const canPay = item.status !== 'paid' && item.status !== 'cancelled' && (item.remaining_minor ?? item.amount_minor - item.paid_minor) > 0
        return <div className="schedule-row" key={item.id}>
          <strong>{dateLabel(item.due_date)}</strong>
          <span>{formatMoney(item.amount_minor)}{(item.principal_minor != null || item.interest_minor != null) && <small>Долг {formatMoney(item.principal_minor ?? 0)} · проценты {formatMoney(item.interest_minor ?? 0)}</small>}</span>
          <span>{formatMoney(item.paid_minor)}</span>
          <span>{statusBadge(item.status)}<span className="schedule-actions">{canPay && <Button variant="secondary" onClick={() => { resetActions(); setPayingItem(item); setAdding(false); setEditingItem(null); reset() }} disabled={Boolean(payingItem) || adding || Boolean(editingItem)}>Внести платёж</Button>}<button className="icon-button" aria-label={`Изменить строку ${dateLabel(item.due_date)}`} title="Изменить" onClick={()=>openEdit(item)} disabled={Boolean(payingItem)||adding||Boolean(editingItem)}><Pencil/></button><button className="icon-button" aria-label={`${item.status==='cancelled'?'Восстановить':'Отменить'} строку ${dateLabel(item.due_date)}`} title={item.status==='cancelled'?'Восстановить':'Отменить'} onClick={()=>{
            resetActions()
            if(item.status==='cancelled'||window.confirm(`Отменить платёж по графику от ${dateLabel(item.due_date)}? Строка останется в истории.`))state.mutate({item,status:item.status==='cancelled'?'planned':'cancelled'})
          }}>{item.status==='cancelled'?<RotateCcw/>:<Ban/>}</button><button className="icon-button icon-button--danger" aria-label={`Удалить строку ${dateLabel(item.due_date)}`} title="Удалить" onClick={()=>{
            resetActions()
            if(window.confirm(`Удалить строку графика от ${dateLabel(item.due_date)} безвозвратно?`))remove.mutate(item)
          }}><Trash2/></button></span></span>
        </div>
      })}
    </div> : !adding && <State title="График пока пуст">Добавьте даты и суммы из банковского графика вручную или импортируйте CSV.</State>)}
  </Modal>
}
