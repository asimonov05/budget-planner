import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Archive, ArrowRight, Ban, CalendarPlus, CirclePlus, Link2, Pencil, RotateCcw, Search, Trash2 } from 'lucide-react'
import { ApiError, api, asList, jsonBody, queryString } from '../lib/api'
import { dateLabel, formatMoney, parseMoney } from '../lib/format'
import { convertMinor, moneyInput, type FxQuote } from '../lib/currency'
import type { Account, Category, ID, ListResponse, Loan, LoanScheduleItem, Tag, Transaction, Transfer } from '../lib/types'
import { Badge, Button, ErrorState, Field, Input, Modal, PageHeader, Select, State } from '../components/ui'
import { AutoLoanProjection } from '../components/AutoLoanProjection'
import { SalaryIncomeSummary } from '../components/SalaryIncomeSummary'
import { CurrencySelect } from '../components/CurrencySelect'

type ResourceType = 'income' | 'payment' | 'transaction' | 'loan'
interface PlanItem {
  id: ID; kind: 'income' | 'expense'; title: string; amount_minor: number; currency?: string; date?: string; month?: string;
  start_date?: string; recurrence: string; certainty: string; status: string; account_id?: ID;
  category_id?: ID; loan_id?: ID | null; tags?: Tag[]; comment?: string; end_date?: string; version?: number
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
  loan_id: z.string().optional(), annual_rate_percent: z.string().optional(), interest_method: z.string().optional(),
  schedule_mode: z.string().optional(), first_payment_date: z.string().optional(), prepayment_strategy: z.string().optional(),
  payment_currency: z.string().optional(), plan_currency: z.string().optional(), exchange_rate: z.string().optional(),
})
type FormValues = z.infer<typeof baseSchema>
interface ResourceSubmission { values: FormValues; idempotencyKey: string; item?: EditableItem }

function newIdempotencyKey(scope: string) {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `${scope}-${random}`
}

function numericIds(values?: string[]) { return (values ?? []).map(Number) }
function rateInput(bps?: number | null) { return bps == null ? '' : (bps / 100).toString().replace('.', ',') }
function parseRateBps(value?: string) {
  if (!value?.trim()) return null
  const normalized = value.trim().replace(',', '.')
  if (!/^\d{1,4}(\.\d{1,2})?$/.test(normalized)) throw new Error('Укажите ставку с точностью до 0,01%')
  const result = Math.round(Number(normalized) * 100)
  if (result > 100_000) throw new Error('Ставка должна быть не выше 1000%')
  return result
}
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

function schemaFor(type: ResourceType, accounts: Account[]) {
  return baseSchema.superRefine((values, context) => {
    const isTransfer = type === 'transaction' && values.transaction_type === 'transfer'
    const sourceAccount = accounts.find((account) => String(account.id) === values.account_id)
    const targetAccount = accounts.find((account) => String(account.id) === values.to_account_id)
    const sourceCurrency = isTransfer ? sourceAccount?.currency ?? 'RUB' :
      type === 'transaction' && (values.transaction_type === 'expense' || values.transaction_type === 'refund')
        ? values.payment_currency || sourceAccount?.currency || 'RUB'
        : type === 'income' || type === 'payment'
          ? values.plan_currency || sourceAccount?.currency || 'RUB'
          : sourceAccount?.currency || 'RUB'
    if (!isTransfer && !values.title?.trim()) context.addIssue({ code: z.ZodIssueCode.custom, path: ['title'], message: 'Укажите название' })
    if (type !== 'loan') {
      try {
        const amount = values.amount ? parseMoney(values.amount, sourceCurrency) : 0
        const signedAdjustment = type === 'transaction' && values.transaction_type === 'adjustment'
        if (signedAdjustment ? amount === 0 : amount <= 0) throw new Error()
      } catch {
        context.addIssue({ code: z.ZodIssueCode.custom, path: ['amount'], message: values.transaction_type === 'adjustment' ? 'Укажите ненулевую корректировку со знаком' : 'Укажите сумму больше нуля' })
      }
    } else if (values.amount) {
      try { parseMoney(values.amount) } catch { context.addIssue({ code: z.ZodIssueCode.custom, path: ['amount'], message: 'Проверьте сумму' }) }
    }
    if (type === 'loan') {
      try { parseRateBps(values.annual_rate_percent) } catch (error) {
        context.addIssue({ code: z.ZodIssueCode.custom, path: ['annual_rate_percent'], message: (error as Error).message })
      }
      if (values.schedule_mode === 'auto') {
        if (!values.amount?.trim() || !values.principal_as_of || !values.first_payment_date || !values.end_date || !values.annual_rate_percent?.trim()) {
          context.addIssue({ code: z.ZodIssueCode.custom, path: ['annual_rate_percent'], message: 'Для расчёта заполните долг, дату остатка, ставку, первый платёж и срок' })
        }
      }
    }
    if (type === 'transaction') {
      if (!values.date) context.addIssue({ code: z.ZodIssueCode.custom, path: ['date'], message: 'Укажите дату' })
      if (!values.account_id) context.addIssue({ code: z.ZodIssueCode.custom, path: ['account_id'], message: 'Выберите счёт' })
      if (isTransfer && !values.to_account_id) context.addIssue({ code: z.ZodIssueCode.custom, path: ['to_account_id'], message: 'Выберите счёт зачисления' })
      if (isTransfer && values.account_id && values.to_account_id === values.account_id) context.addIssue({ code: z.ZodIssueCode.custom, path: ['to_account_id'], message: 'Счета перевода должны отличаться' })
      if (values.transaction_type === 'adjustment' && !values.comment?.trim()) context.addIssue({ code: z.ZodIssueCode.custom, path: ['comment'], message: 'Для корректировки нужен комментарий' })
      const targetCurrency = isTransfer ? targetAccount?.currency : sourceAccount?.currency
      const needsRate = Boolean(values.amount && targetCurrency && sourceCurrency !== targetCurrency && (isTransfer || values.transaction_type === 'expense' || values.transaction_type === 'refund'))
      if (needsRate) {
        try {
          const converted = convertMinor(parseMoney(values.amount!, sourceCurrency), sourceCurrency, targetCurrency!, values.exchange_rate ?? '')
          if (converted <= 0) throw new Error('Сумма после конвертации должна быть положительной')
        } catch (error) {
          context.addIssue({ code: z.ZodIssueCode.custom, path: ['exchange_rate'], message: (error as Error).message })
        }
      }
    }
    if ((type === 'income' || type === 'payment') && sourceAccount && values.plan_currency && values.plan_currency !== (sourceAccount.currency ?? 'RUB')) {
      context.addIssue({ code: z.ZodIssueCode.custom, path: ['plan_currency'], message: 'Валюта плана должна совпадать с валютой счёта' })
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
function resourceAmount(item: Item) { return 'amount_minor' in item ? 'merchant_amount_minor' in item && item.merchant_amount_minor != null ? item.merchant_amount_minor : item.amount_minor : item.next_payment_minor ?? item.remaining_payments_minor ?? item.principal_minor ?? 0 }
function resourceCurrency(item: Item, accountCurrencies: Map<string, string>) {
  if ('name' in item) return 'RUB'
  if ('type' in item) return item.merchant_currency ?? item.account_currency ?? accountCurrencies.get(String(item.account_id)) ?? 'RUB'
  return item.currency ?? accountCurrencies.get(String(item.account_id)) ?? 'RUB'
}
function resourceDate(item: Item) { return 'date' in item ? item.date : 'name' in item ? item.next_payment_date ?? item.start_date : undefined }
function resourceSubtitle(item: Item, type: ResourceType, loanNames: Map<string, string>) {
  if ('merchant_currency' in item && item.merchant_currency && item.merchant_amount_minor != null) {
    const accountCurrency = item.account_currency ?? 'RUB'
    return `${item.type === 'refund' ? 'На счёт +' : 'Со счёта −'}${formatMoney(item.amount_minor, accountCurrency)} · курс ${item.merchant_exchange_rate ?? '—'} ${accountCurrency} за 1 ${item.merchant_currency}`
  }
  if (type === 'loan' && 'name' in item) {
    return [
      item.creditor,
      item.annual_rate_bps == null ? null : `${rateInput(item.annual_rate_bps)}% годовых`,
      item.schedule_mode === 'auto' ? 'Аннуитетный график' : 'Ручной график',
    ].filter(Boolean).join(' · ')
  }
  if ('loan_id' in item && item.loan_id != null) {
    const name = loanNames.get(String(item.loan_id)) ?? `Кредит ${item.loan_id}`
    if ('principal_component_minor' in item && (item.principal_component_minor != null || item.interest_component_minor != null)) {
      return `${name} · долг ${formatMoney(item.principal_component_minor ?? 0)} · проценты ${formatMoney(item.interest_component_minor ?? 0)}`
    }
    return `Кредит: ${name}`
  }
  return 'recurrence' in item && item.recurrence !== 'none'
    ? `Повтор: ${item.recurrence === 'monthly' ? 'ежемесячно' : 'ежегодно'}`
    : 'Разовая запись'
}

export function ResourcePage({ type }: { type: ResourceType }) {
  const config = configs[type]; const client = useQueryClient(); const [open, setOpen] = useState(false); const [quickTransfer, setQuickTransfer] = useState(false); const [editing, setEditing] = useState<EditableItem | null>(null); const [search, setSearch] = useState(''); const [page, setPage] = useState(1); const [scheduleLoan, setScheduleLoan] = useState<Loan | null>(null); const [matchingPlan, setMatchingPlan] = useState<PlanItem | null>(null); const [linkingTransaction, setLinkingTransaction] = useState<Transaction | null>(null); const [transferSaved, setTransferSaved] = useState(false)
  const pageSize = 100
  const filter = type === 'income' ? { kind: 'income' } : type === 'payment' ? { kind: 'expense' } : type === 'transaction' ? { limit: pageSize, offset: (page - 1) * pageSize } : { include_archived: true }
  const list = useQuery<Item[] | ListResponse<Item>>({ queryKey: [config.endpoint, filter], queryFn: () => api(`${config.endpoint}?${queryString(filter)}`) })
  const accounts = useQuery<Account[] | ListResponse<Account>>({ queryKey: ['accounts', { include_archived: true }], queryFn: () => api('/accounts?include_archived=true') })
  const categories = useQuery<Category[] | ListResponse<Category>>({ queryKey: ['categories', { include_archived: true }], queryFn: () => api('/categories?include_archived=true') })
  const tags = useQuery<Tag[] | ListResponse<Tag>>({ queryKey: ['tags', { include_archived: true }], queryFn: () => api('/tags?include_archived=true'), enabled: type !== 'loan' })
  const linkedLoans = useQuery<Loan[] | ListResponse<Loan>>({ queryKey: ['loans', { include_archived: true }], queryFn: () => api('/loans?include_archived=true'), enabled: type === 'payment' || type === 'transaction' })
  const transfers = useQuery<Transfer[] | ListResponse<Transfer>>({ queryKey: ['/transfers'], queryFn: () => api('/transfers'), enabled: type === 'transaction' })
  const items = asList(list.data).filter((item) => resourceName(item).toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')))
  const loanItems = type === 'loan' ? asList(list.data) as Loan[] : asList(linkedLoans.data)
  const loanNames = new Map(loanItems.map((loan) => [String(loan.id), loan.name]))
  const activeScheduleLoan = scheduleLoan ? loanItems.find((loan) => String(loan.id) === String(scheduleLoan.id)) ?? scheduleLoan : null
  const accountNames = new Map(asList(accounts.data).map((account) => [String(account.id), account.name]))
  const accountCurrencies = new Map(asList(accounts.data).map((account) => [String(account.id), account.currency ?? 'RUB']))
  const baseCurrency = (!Array.isArray(accounts.data) ? (accounts.data as { base_currency?: string } | undefined)?.base_currency : undefined) ?? 'RUB'
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
      client.invalidateQueries({ queryKey: ['/loans'] }),
      client.invalidateQueries({ queryKey: ['loans'] }),
      ...(includeTransfers ? [client.invalidateQueries({ queryKey: ['/transfers'] })] : []),
    ])
  }
  const accountCurrency = (id?: string) => asList(accounts.data).find((account) => String(account.id) === id)?.currency ?? 'RUB'
  const transactionAmounts = (values: FormValues) => {
    const accountUnit = accountCurrency(values.account_id)
    const purchaseUnit = values.transaction_type === 'expense' || values.transaction_type === 'refund'
      ? values.payment_currency || accountUnit
      : accountUnit
    const purchaseMinor = parseMoney(values.amount!, purchaseUnit)
    const converted = purchaseUnit !== accountUnit
    return {
      amount_minor: converted ? convertMinor(purchaseMinor, purchaseUnit, accountUnit, values.exchange_rate ?? '') : purchaseMinor,
      merchant_currency: converted ? purchaseUnit : null,
      merchant_amount_minor: converted ? purchaseMinor : null,
      merchant_exchange_rate: converted ? values.exchange_rate?.trim().replace(',', '.') : null,
    }
  }
  const save = useMutation<unknown, Error, ResourceSubmission>({ mutationFn: ({ values, idempotencyKey, item }) => {
    const sourceCurrency = accountCurrency(values.account_id)
    const planCurrency = values.plan_currency || sourceCurrency
    if (item) {
      if ('from_account_id' in item) return api(`/transfers/${item.id}`, { method: 'PATCH', body: jsonBody({
        from_account_id: Number(values.account_id), to_account_id: Number(values.to_account_id),
        amount_minor: parseMoney(values.amount!, sourceCurrency), exchange_rate: sourceCurrency === accountCurrency(values.to_account_id) ? null : values.exchange_rate?.trim().replace(',', '.') || null,
        date: values.date, comment: values.comment?.trim() || null, version: itemVersion(item),
      }) })
      if (type === 'loan') return api(`/loans/${item.id}`, { method: 'PATCH', body: jsonBody({ name: values.title!.trim(), creditor: values.creditor?.trim() || null, principal_minor: values.amount?.trim() ? parseMoney(values.amount) : null, principal_as_of: values.principal_as_of || null, annual_rate_bps: parseRateBps(values.annual_rate_percent), interest_method: values.interest_method || 'simple', schedule_mode: values.schedule_mode || 'manual', first_payment_date: values.first_payment_date || null, account_id: values.account_id ? Number(values.account_id) : null, start_date: values.start_date || null, end_date: values.end_date || null, comment: values.comment?.trim() || null, version: itemVersion(item) }) })
      if (type === 'transaction') return api(`/transactions/${item.id}`, { method: 'PATCH', body: jsonBody({
        ...transactionAmounts(values), date: values.date,
        category_id: values.category_id ? Number(values.category_id) : null,
        description: values.title!.trim(), comment: values.comment?.trim() || null,
        tag_ids: numericIds(values.tag_ids), version: itemVersion(item),
      }) })
      return api(`/plan-items/${item.id}`, { method: 'PATCH', body: jsonBody({ title: values.title!.trim(), amount_minor: parseMoney(values.amount!, planCurrency), end_date: values.end_date || null, certainty: values.certainty || 'confirmed', account_id: values.account_id ? Number(values.account_id) : null, category_id: values.category_id ? Number(values.category_id) : null, loan_id: values.loan_id ? Number(values.loan_id) : null, tag_ids: numericIds(values.tag_ids), comment: values.comment?.trim() || null, version: itemVersion(item) }) })
    }
    if (type === 'loan') return api(config.endpoint, { method: 'POST', body: jsonBody({ name: values.title!.trim(), creditor: values.creditor?.trim() || null, principal_minor: values.amount?.trim() ? parseMoney(values.amount) : null, principal_as_of: values.principal_as_of || null, annual_rate_bps: parseRateBps(values.annual_rate_percent), interest_method: values.interest_method || 'simple', schedule_mode: values.schedule_mode || 'manual', first_payment_date: values.first_payment_date || null, account_id: values.account_id ? Number(values.account_id) : null, start_date: values.start_date || null, end_date: values.end_date || null, comment: values.comment?.trim() || null }) })
    if (type === 'transaction' && values.transaction_type === 'transfer') return api('/transfers', { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: jsonBody({
      from_account_id: Number(values.account_id), to_account_id: Number(values.to_account_id),
      amount_minor: parseMoney(values.amount!, sourceCurrency), exchange_rate: sourceCurrency === accountCurrency(values.to_account_id) ? null : values.exchange_rate?.trim().replace(',', '.') || null,
      date: values.date, comment: values.comment || null,
    }) })
    if (type === 'transaction') return api(config.endpoint, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: jsonBody({
      type: values.transaction_type || 'expense', ...transactionAmounts(values), date: values.date,
      account_id: Number(values.account_id), category_id: values.category_id ? Number(values.category_id) : null,
      ...(values.loan_id ? { loan_id: Number(values.loan_id), prepayment_strategy: values.prepayment_strategy || null } : {}),
      description: values.title!.trim(), comment: values.comment || null, tag_ids: numericIds(values.tag_ids),
    }) })
    const recurrence = values.recurrence || 'none'
    return api(config.endpoint, { method: 'POST', body: jsonBody({ kind: type === 'income' ? 'income' : 'expense', title: values.title!.trim(), amount_minor: parseMoney(values.amount!, planCurrency), currency: planCurrency, date: values.date || null, month: values.date ? null : values.month, recurrence, start_date: recurrence === 'none' ? null : values.date, end_date: values.end_date || null, certainty: values.certainty || 'confirmed', account_id: values.account_id ? Number(values.account_id) : null, category_id: values.category_id ? Number(values.category_id) : null, loan_id: type === 'payment' && values.loan_id ? Number(values.loan_id) : null, funding_source: 'free', tag_ids: numericIds(values.tag_ids), comment: values.comment?.trim() || null }) })
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
  const unlinkLoan = useMutation<unknown, Error, Transaction>({
    mutationFn: (transaction) => api(`/loans/${transaction.loan_id}/transactions/${transaction.id}/link?${queryString({ version: itemVersion(transaction) })}`, { method: 'DELETE' }),
    onSuccess: () => invalidate(),
  })
  const editItem = (item: EditableItem) => { save.reset(); changeState.reset(); remove.reset(); setTransferSaved(false); setOpen(false); setEditing(item) }
  const deleteItem = (endpoint: string, item: EditableItem, label: string) => {
    remove.reset()
    if (window.confirm(`Удалить «${label}» безвозвратно? Если запись связана с историей, сервер не позволит удаление.`)) remove.mutate({ endpoint, item })
  }
  const mutationError = actionError(changeState.error ?? remove.error ?? unlinkLoan.error)
  return <div className="page"><PageHeader eyebrow={config.eyebrow} title={config.title} description={config.description} actions={<>{type === 'transaction' && <Button variant="secondary" onClick={() => { save.reset(); changeState.reset(); remove.reset(); setEditing(null); setQuickTransfer(true); setTransferSaved(false); setOpen(true) }}><ArrowRight/> Перевод между счетами</Button>}<Button onClick={() => { save.reset(); changeState.reset(); remove.reset(); setEditing(null); setQuickTransfer(false); setTransferSaved(false); setOpen(true) }}><CirclePlus/> {config.add}</Button></>} />
    {type === 'income' && <SalaryIncomeSummary/>}
    <div className="list-toolbar"><label className="search"><Search/><input placeholder="Поиск" value={search} onChange={(e) => setSearch(e.target.value)}/></label>{type === 'transaction' && <Badge tone="neutral">Переводы не входят в доходы и расходы</Badge>}</div>
    {transferSaved && <div className="notice notice--calm"><ArrowRight/><div><strong>Перевод сохранён</strong><span>Деньги перемещены между счетами без изменения общих доходов и расходов.</span></div></div>}
    {mutationError && <div className="form-alert" role="alert">{mutationError}</div>}
    {list.isLoading && <State kind="loading" title="Загружаем данные"/>}{list.isError && <ErrorState error={list.error} retry={() => list.refetch()}/>}
    {!list.isLoading && !list.isError && (items.length ? <div className="data-card">
      <div className="data-list data-list--header"><span>Название</span><span>Дата</span><span>Статус / тип</span><span>{type === 'loan' ? 'Остаток долга' : 'Сумма'}</span><span/></div>
      {items.map((item) => <div className="data-list" key={item.id}>
        <div><strong>{resourceName(item)}</strong><small>{resourceSubtitle(item, type, loanNames)}</small></div>
        <span>{dateLabel(resourceDate(item))}</span>
        <span>{type === 'loan' && 'archived' in item && item.archived ? statusBadge('archived') : 'status' in item ? statusBadge(item.status) : 'type' in item ? statusBadge(item.type) : statusBadge(item.status)}</span>
        <strong className={(('kind' in item && item.kind === 'income') || ('type' in item && item.type === 'income')) ? 'positive' : ''}>{formatMoney(resourceAmount(item), resourceCurrency(item, accountCurrencies))}</strong>
        <div className="row-actions">
          {type === 'loan' && !(item as Loan).archived && <button className="icon-button" aria-label={`График кредита ${resourceName(item)}`} title="График" onClick={() => setScheduleLoan(item as Loan)}><CalendarPlus/></button>}
          {(type === 'income' || type === 'payment') && <button className="icon-button" aria-label={`Сверить с фактом ${resourceName(item)}`} title="Сверить" onClick={() => setMatchingPlan(item as PlanItem)}><ArrowRight/></button>}
          {type === 'transaction' && (item as Transaction).type === 'expense' && (accountCurrencies.get(String((item as Transaction).account_id)) ?? (item as Transaction).account_currency ?? baseCurrency) === baseCurrency && (item as Transaction).loan_id == null && !(item as Transaction).external_source?.startsWith('loan_schedule:') && <button className="icon-button" aria-label={`Связать с кредитом ${resourceName(item)}`} title="Связать с кредитом" onClick={() => setLinkingTransaction(item as Transaction)}><Link2/></button>}
          {type === 'transaction' && (item as Transaction).loan_id != null && (item as Transaction).loan_balance_applied === false && <button className="icon-button" aria-label={`Отвязать от кредита ${resourceName(item)}`} title="Отвязать от кредита" onClick={() => { if (window.confirm(`Убрать связь операции «${resourceName(item)}» с кредитом?`)) unlinkLoan.mutate(item as Transaction) }}><Link2/></button>}
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
          <div><strong>{accountNames.get(String(transfer.from_account_id)) ?? `Счёт ${transfer.from_account_id}`} → {accountNames.get(String(transfer.to_account_id)) ?? `Счёт ${transfer.to_account_id}`}</strong><small>{transfer.comment || `Курс: 1 ${accountCurrencies.get(String(transfer.from_account_id)) ?? 'RUB'} = ${transfer.exchange_rate ?? 1} ${accountCurrencies.get(String(transfer.to_account_id)) ?? 'RUB'}`}</small></div>
          <span>{dateLabel(transfer.date)}</span><span><Badge tone="neutral">Перевод</Badge></span><strong>{formatMoney(transfer.amount_minor, accountCurrencies.get(String(transfer.from_account_id)) ?? 'RUB')} → {formatMoney(transfer.to_amount_minor ?? transfer.amount_minor, accountCurrencies.get(String(transfer.to_account_id)) ?? 'RUB')}</strong><div className="row-actions"><button className="icon-button" aria-label={`Изменить перевод ${transfer.id}`} title="Изменить" onClick={() => editItem(transfer)}><Pencil/></button><button className="icon-button icon-button--danger" aria-label={`Удалить перевод ${transfer.id}`} title="Удалить" onClick={() => deleteItem('/transfers', transfer, `перевод от ${dateLabel(transfer.date)}`)}><Trash2/></button></div>
        </div>)}
      </div> : <State title={asList(transfers.data).length ? 'Переводы не найдены' : 'Переводов пока нет'}>{asList(transfers.data).length ? 'Измените строку поиска.' : 'Нажмите «Перевод между счетами», чтобы создать первый перевод.'}</State>)}
    </section>}
    {(open || editing) && <ResourceForm type={type} item={editing ?? undefined} initialTransactionType={quickTransfer ? 'transfer' : undefined} accounts={asList(accounts.data)} categories={asList(categories.data)} tags={asList(tags.data)} loans={loanItems} baseCurrency={baseCurrency} mutation={save} onClose={() => { setOpen(false); setEditing(null); setQuickTransfer(false) }}/>}
    {matchingPlan && <PlanMatchForm plan={matchingPlan} onClose={() => setMatchingPlan(null)} />}
    {linkingTransaction && <LoanTransactionLinkForm transaction={linkingTransaction} loans={loanItems} onClose={() => setLinkingTransaction(null)} />}
    {activeScheduleLoan && (activeScheduleLoan.schedule_mode === 'auto' ? <AutoLoanProjection loan={activeScheduleLoan} onClose={() => setScheduleLoan(null)} /> : <LoanSchedule loan={activeScheduleLoan} accounts={asList(accounts.data)} categories={asList(categories.data)} onClose={() => setScheduleLoan(null)} />)}
  </div>
}

function resourceDefaults(type: ResourceType, item?: EditableItem, initialTransactionType = 'expense', accounts: Account[] = [], baseCurrency = 'RUB'): FormValues {
  const accountCurrency = (id?: ID | null) => accounts.find((account) => String(account.id) === String(id))?.currency ?? baseCurrency
  if (!item) return { certainty: 'confirmed', recurrence: 'none', transaction_type: initialTransactionType, interest_method: 'simple', schedule_mode: 'manual', loan_id: '', prepayment_strategy: '', payment_currency: '', plan_currency: baseCurrency, exchange_rate: '', tag_ids: [] }
  if ('from_account_id' in item) return {
    transaction_type: 'transfer', amount: moneyInput(item.amount_minor, accountCurrency(item.from_account_id)), date: item.date,
    account_id: String(item.from_account_id), to_account_id: String(item.to_account_id), exchange_rate: String(item.exchange_rate ?? '1'), comment: item.comment ?? '', tag_ids: [],
  }
  if (type === 'loan') {
    const loan = item as Loan
    return { title: loan.name, creditor: loan.creditor ?? '', amount: loan.principal_minor == null ? '' : moneyInput(loan.principal_minor), principal_as_of: loan.principal_as_of ?? '', annual_rate_percent: rateInput(loan.annual_rate_bps), interest_method: loan.interest_method ?? 'simple', schedule_mode: loan.schedule_mode ?? 'manual', first_payment_date: loan.first_payment_date ?? '', account_id: loan.account_id == null ? '' : String(loan.account_id), start_date: loan.start_date ?? '', end_date: loan.end_date ?? '', comment: loan.comment ?? '', tag_ids: [] }
  }
  if (type === 'transaction') {
    const transaction = item as Transaction
    const currency = transaction.merchant_currency ?? accountCurrency(transaction.account_id)
    const amount = transaction.merchant_amount_minor ?? transaction.amount_minor
    return { title: transaction.description ?? '', amount: moneyInput(amount, currency), payment_currency: currency, exchange_rate: transaction.merchant_exchange_rate == null ? '' : String(transaction.merchant_exchange_rate), date: transaction.date, account_id: transaction.account_id == null ? '' : String(transaction.account_id), category_id: transaction.category_id == null ? '' : String(transaction.category_id), loan_id: transaction.loan_id == null ? '' : String(transaction.loan_id), prepayment_strategy: transaction.prepayment_strategy ?? '', transaction_type: transaction.type, comment: transaction.comment ?? '', tag_ids: transaction.tags?.map((tag) => String(tag.id)) ?? [] }
  }
  const plan = item as PlanItem
  return { title: plan.title, amount: moneyInput(plan.amount_minor, plan.currency ?? baseCurrency), plan_currency: plan.currency ?? baseCurrency, date: plan.date ?? plan.start_date ?? '', month: plan.month ?? '', account_id: plan.account_id == null ? '' : String(plan.account_id), category_id: plan.category_id == null ? '' : String(plan.category_id), loan_id: plan.loan_id == null ? '' : String(plan.loan_id), recurrence: plan.recurrence, certainty: plan.certainty, end_date: plan.end_date ?? '', comment: plan.comment ?? '', tag_ids: plan.tags?.map((tag) => String(tag.id)) ?? [] }
}

function ResourceForm({ type, item, initialTransactionType, accounts, categories, tags, loans, baseCurrency, mutation, onClose }: { type: ResourceType; item?: EditableItem; initialTransactionType?: string; accounts: Account[]; categories: Category[]; tags: Tag[]; loans: Loan[]; baseCurrency: string; mutation: ReturnType<typeof useMutation<unknown, Error, ResourceSubmission>>; onClose: () => void }) {
  const submissionKey = useRef<string | null>(null)
  const { register, handleSubmit, watch, setValue, getValues, formState: { errors, isDirty } } = useForm<FormValues>({ resolver: zodResolver(schemaFor(type, accounts)), defaultValues: resourceDefaults(type, item, initialTransactionType, accounts, baseCurrency) })
  const transactionType = watch('transaction_type')
  const accountId = watch('account_id')
  const toAccountId = watch('to_account_id')
  const paymentCurrencyValue = watch('payment_currency')
  const planCurrencyValue = watch('plan_currency')
  const amountValue = watch('amount')
  const entryDate = watch('date')
  const exchangeRate = watch('exchange_rate')
  const recurrence = watch('recurrence')
  const loanId = watch('loan_id')
  const scheduleMode = watch('schedule_mode')
  const isTransfer = type === 'transaction' && transactionType === 'transfer'
  const sourceCurrency = accounts.find((account) => String(account.id) === accountId)?.currency ?? 'RUB'
  const targetCurrency = accounts.find((account) => String(account.id) === toAccountId)?.currency ?? 'RUB'
  const paymentCurrency = paymentCurrencyValue || sourceCurrency
  const isPayment = type === 'transaction' && !isTransfer && (transactionType === 'expense' || transactionType === 'refund')
  const conversionFrom = isTransfer ? sourceCurrency : paymentCurrency
  const conversionTo = isTransfer ? targetCurrency : sourceCurrency
  const needsConversion = (isTransfer && Boolean(accountId && toAccountId) || isPayment && Boolean(accountId)) && conversionFrom !== conversionTo
  const pairKey = `${conversionFrom}/${conversionTo}/${entryDate ?? ''}`
  const previousPair = useRef(pairKey)
  useEffect(() => {
    if (previousPair.current !== pairKey) {
      previousPair.current = pairKey
      setValue('exchange_rate', '', { shouldDirty: true })
    }
  }, [pairKey, setValue])
  const quote = useQuery<FxQuote>({
    queryKey: ['currency-quote', conversionFrom, conversionTo, entryDate],
    queryFn: () => api(`/currencies/quote?${queryString({ from_currency: conversionFrom, to_currency: conversionTo, on_date: entryDate })}`),
    enabled: Boolean(needsConversion && entryDate), retry: false,
  })
  useEffect(() => {
    if (quote.data && !getValues('exchange_rate')) setValue('exchange_rate', quote.data.rate)
  }, [quote.data, getValues, setValue])
  let conversionPreview: string | null = null
  if (needsConversion && amountValue && exchangeRate) {
    try {
      const entered = parseMoney(amountValue, conversionFrom)
      conversionPreview = formatMoney(convertMinor(entered, conversionFrom, conversionTo, exchangeRate), conversionTo)
    } catch { /* validation is shown beside the rate field */ }
  }
  let accountPreview: string | null = conversionPreview
  let sourcePreview: string | null = null
  if (isTransfer && amountValue) {
    try { sourcePreview = formatMoney(parseMoney(amountValue, sourceCurrency), sourceCurrency) } catch { /* form validation follows */ }
  }
  if (!needsConversion && amountValue && accountId && (isPayment || isTransfer)) {
    try { accountPreview = formatMoney(parseMoney(amountValue, sourceCurrency), sourceCurrency) } catch { /* form validation follows */ }
  }
  const enteredCurrency = isTransfer ? sourceCurrency : isPayment ? paymentCurrency :
    type === 'income' || type === 'payment' ? planCurrencyValue || sourceCurrency :
    type === 'loan' ? 'RUB' : sourceCurrency
  useEffect(() => {
    if (loanId && (type === 'payment' ? enteredCurrency : sourceCurrency) !== baseCurrency) {
      setValue('loan_id', '', { shouldDirty: true })
    }
  }, [loanId, type, enteredCurrency, sourceCurrency, baseCurrency, setValue])
  useEffect(() => {
    if ((type === 'income' || type === 'payment') && accountId) {
      setValue('plan_currency', sourceCurrency, { shouldDirty: true })
    }
  }, [type, accountId, sourceCurrency, setValue])
  const isEditing = Boolean(item)
  const linkedTransaction = type === 'transaction' && item != null && 'loan_id' in item && item.loan_id != null
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
  const availableLoans = loans.filter((loan) => !loan.archived || String(loan.id) === loanId)
  const selectedLoan = availableLoans.find((loan) => String(loan.id) === loanId)
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
    <Field label={type === 'loan' ? 'Известный основной долг' : isTransfer ? `Списать, ${enteredCurrency}` : isPayment ? `Сумма оплаты, ${enteredCurrency}` : `Сумма, ${enteredCurrency}`} error={errors.amount?.message} hint={linkedTransaction ? 'Сумма связанного с кредитом платежа защищена' : undefined}><Input inputMode="decimal" {...register('amount')} placeholder="0,00" readOnly={linkedTransaction} /></Field>
    {type !== 'loan' && <Field label="Дата" error={errors.date?.message} hint={isEditing && !isTransfer && type !== 'transaction' ? 'Дата и периодичность плана фиксируются при создании' : linkedTransaction ? 'Дата связанного с кредитом платежа защищена' : undefined}><Input type="date" {...register('date')} readOnly={isEditing && ((type !== 'transaction' && !isTransfer) || linkedTransaction)} /></Field>}
    {(type === 'income' || type === 'payment') && <><Field label="Только месяц" hint="Используйте, если точный день неизвестен"><Input type="month" {...register('month')} readOnly={isEditing} /></Field><Field label="Повторение">{isEditing ? <div className="field-control"><Select value={recurrence} disabled><option value="none">Не повторять</option><option value="monthly">Каждый месяц</option><option value="yearly">Каждый год</option></Select><input type="hidden" {...register('recurrence')} /></div> : <Select {...register('recurrence')}><option value="none">Не повторять</option><option value="monthly">Каждый месяц</option><option value="yearly">Каждый год</option></Select>}</Field><Field label="Дата окончания" hint="Необязательно, для повторяющихся планов"><Input type="date" {...register('end_date')} /></Field></>}
    {type === 'income' && <Field label="Определённость"><Select {...register('certainty')}><option value="confirmed">Подтверждён</option><option value="possible">Возможен</option></Select></Field>}
    {type === 'loan' && <><Field label="Годовая ставка, %" error={errors.annual_rate_percent?.message}><Input inputMode="decimal" {...register('annual_rate_percent')} placeholder="Например, 12,5" /></Field><Field label="Начисление процентов"><Select {...register('interest_method')}><option value="simple">Простые — на остаток долга</option><option value="compound">Сложные — ежедневная капитализация</option></Select></Field><Field label="График"><Select {...register('schedule_mode')}><option value="manual">Ручной график банка</option><option value="auto">Расчётный аннуитетный график</option></Select></Field><Field label="Остаток долга на дату"><Input type="date" {...register('principal_as_of')} /></Field><Field label="Счёт списания"><Select {...register('account_id')}><option value="">Не выбран</option>{availableAccounts.filter((account) => (account.currency ?? 'RUB') === baseCurrency).map((account) => <option key={account.id} value={account.id}>{optionLabel(`${account.name} · ${account.currency ?? 'RUB'}`, account.archived)}</option>)}</Select></Field><Field label="Дата начала"><Input type="date" {...register('start_date')} /></Field>{scheduleMode === 'auto' && <Field label="Первый платёж"><Input type="date" {...register('first_payment_date')} /></Field>}<Field label="Дата окончания"><Input type="date" {...register('end_date')} /></Field><p className="form-hint form-span">Расчёт использует фактические дни в году. Сверяйте суммы с графиком банка: правила округления и капитализации могут отличаться.</p></>}
    {type !== 'loan' && <Field label={isTransfer ? 'Со счёта' : 'Счёт'} error={errors.account_id?.message} hint={isEditing && type === 'transaction' && !isTransfer ? 'Счёт сохранённой операции нельзя изменить' : undefined}>{isEditing && type === 'transaction' && !isTransfer ? <div className="field-control"><Select value={accountId} disabled><option value="">Не выбран</option>{availableAccounts.map((account) => <option key={account.id} value={account.id}>{optionLabel(`${account.name} · ${account.currency ?? 'RUB'}`, account.archived)}</option>)}</Select><input type="hidden" {...register('account_id')} /></div> : <Select {...register('account_id')}><option value="">Не выбран</option>{availableAccounts.map((account) => <option key={account.id} value={account.id}>{optionLabel(`${account.name} · ${account.currency ?? 'RUB'}`, account.archived)}</option>)}</Select>}</Field>}
    {isPayment && <Field label="Валюта оплаты" hint="Сумма выше будет показана в этой валюте"><CurrencySelect value={paymentCurrency} onChange={(value) => setValue('payment_currency', value, { shouldDirty: true })}/></Field>}
    {(type === 'income' || type === 'payment') && <Field label="Валюта плана" error={errors.plan_currency?.message} hint={accountId ? 'Совпадает с валютой выбранного счёта' : 'Без счёта выберите валюту плана'}><CurrencySelect value={planCurrencyValue || sourceCurrency} onChange={(value) => setValue('plan_currency', value, { shouldDirty: true })} disabled={Boolean(accountId)}/></Field>}
    {(type === 'payment' || (type === 'transaction' && transactionType === 'expense')) && (type === 'payment' ? enteredCurrency : sourceCurrency) === baseCurrency && <Field label="Кредит" hint={type === 'transaction' ? 'Для ручного графика вносите факт через карточку кредита' : selectedLoan?.schedule_mode === 'auto' && selectedLoan.annuity_payment_minor != null ? `Расчётный аннуитетный платёж: ${formatMoney(selectedLoan.annuity_payment_minor)}. В прогнозе учитывается график кредита.` : 'Связанный платёж не дублируется с графиком кредита'}><Select {...register('loan_id')} disabled={type === 'transaction' && isEditing}><option value="">Не связан</option>{availableLoans.filter((loan) => type === 'payment' || loan.schedule_mode === 'auto' || String(loan.id) === loanId).map((loan) => <option key={loan.id} value={loan.id}>{optionLabel(loan.name, loan.archived)}</option>)}</Select></Field>}
    {type === 'transaction' && !isEditing && transactionType === 'expense' && loanId && <Field label="Досрочное погашение" hint="Если платёж сверх обычного, выберите способ пересчёта"><Select {...register('prepayment_strategy')}><option value="">Обычный платёж</option><option value="reduce_term">Сократить срок</option><option value="reduce_payment">Уменьшить платёж</option></Select></Field>}
    {isTransfer && <Field label="На счёт" error={errors.to_account_id?.message}><Select {...register('to_account_id')}><option value="">Не выбран</option>{availableAccounts.map((account) => <option key={account.id} value={account.id}>{optionLabel(`${account.name} · ${account.currency ?? 'RUB'}`, account.archived)}</option>)}</Select></Field>}
    {needsConversion && <details className="fx-details form-span" open><summary>Параметры конвертации · {conversionFrom} → {conversionTo}</summary><div className="form-stack"><Field label={`Курс: 1 ${conversionFrom} в ${conversionTo}`} error={errors.exchange_rate?.message} hint="Фактический курс банка можно изменить вручную"><Input inputMode="decimal" {...register('exchange_rate')} placeholder="Например, 1,10"/></Field>{quote.isLoading && <small>Получаем официальный курс Банка России…</small>}{quote.data && <small>Подсказка ЦБ на {dateLabel(quote.data.effective_date)}: {quote.data.rate.replace('.', ',')} {conversionTo} за 1 {conversionFrom}. Курс банка может отличаться.</small>}{quote.isError && <small>Курс ЦБ недоступен. Введите фактический курс вручную.</small>}</div></details>}
    {isTransfer && accountId && toAccountId && <p className="fx-preview form-span">Со счёта: −{sourcePreview ?? 'укажите сумму'}<br/>На счёт: +{accountPreview ?? 'укажите сумму и курс'}</p>}
    {isPayment && accountId && <p className="fx-preview form-span">{transactionType === 'refund' ? 'На счёт вернётся' : 'Со счёта спишется'}: {transactionType === 'refund' ? '+' : '−'}{accountPreview ?? 'укажите сумму и курс'} · {sourceCurrency}</p>}
    {type !== 'loan' && !isTransfer && <Field label="Категория"><Select {...register('category_id')}><option value="">Без категории</option>{availableCategories.map((category) => <option key={category.id} value={category.id}>{optionLabel(category.name, category.archived)}</option>)}</Select></Field>}
    {type !== 'loan' && !isTransfer && <Field label="Теги" hint="Можно выбрать несколько с Ctrl или Cmd"><Select multiple size={Math.min(4, Math.max(2, availableTags.length))} {...register('tag_ids')}>{availableTags.map((tag) => <option key={tag.id} value={tag.id}>{optionLabel(tag.name, tag.archived)}</option>)}</Select></Field>}
    {isTransfer && <p className="form-hint form-span">Перевод создаётся одной атомарной операцией и не попадёт в общие доходы или расходы.</p>}
    <Field label="Комментарий" error={errors.comment?.message}><textarea className="input textarea" {...register('comment')} /></Field>
    {mutation.isError && <div className="form-alert form-span" role="alert">{actionError(mutation.error)}</div>}<div className="form-actions form-span"><Button type="button" variant="ghost" onClick={close}>Отмена</Button><Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? 'Сохраняем…' : isEditing ? 'Сохранить изменения' : isTransfer ? 'Перевести' : 'Сохранить'}</Button></div>
  </form></Modal>
}

function LoanTransactionLinkForm({ transaction, loans, onClose }: { transaction: Transaction; loans: Loan[]; onClose: () => void }) {
  const client = useQueryClient()
  const submissionKey = useRef<string | null>(null)
  const [loanId, setLoanId] = useState('')
  const [principal, setPrincipal] = useState('')
  const [interest, setInterest] = useState('')
  const [alreadyReflected, setAlreadyReflected] = useState(true)
  const [strategy, setStrategy] = useState('')
  const [inputError, setInputError] = useState('')
  const selectedLoan = loans.find((loan) => String(loan.id) === loanId)
  const link = useMutation({
    mutationFn: ({ body, key }: { body: Record<string, unknown>; key: string }) => api(`/loans/${loanId}/transactions/${transaction.id}/link`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: jsonBody(body) }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['/transactions'] }),
        client.invalidateQueries({ queryKey: ['/loans'] }),
        client.invalidateQueries({ queryKey: ['forecast'] }),
      ])
      onClose()
    },
  })
  const submit = () => {
    try {
      const principalMinor = optionalMoney(principal)
      const interestMinor = optionalMoney(interest)
      if (!loanId || (principalMinor ?? 0) < 0 || (interestMinor ?? 0) < 0 || (principalMinor ?? 0) + (interestMinor ?? 0) > transaction.amount_minor) {
        setInputError('Выберите кредит и проверьте части платежа')
        return
      }
      if (!alreadyReflected && principalMinor == null) {
        setInputError('Укажите сумму погашения основного долга')
        return
      }
      setInputError('')
      const key = submissionKey.current ?? newIdempotencyKey('loan-link')
      submissionKey.current = key
      link.mutate({ body: {
        principal_minor: principalMinor,
        interest_minor: interestMinor,
        already_reflected_in_balance: alreadyReflected,
        prepayment_strategy: alreadyReflected ? null : strategy || null,
      }, key }, { onSettled: () => { submissionKey.current = null } })
    } catch {
      setInputError('Проверьте суммы платежа')
    }
  }

  return <Modal title={`Связать «${transaction.description || 'операцию'}» с кредитом`} onClose={onClose}>
    <div className="form-stack">
      <p className="form-hint">Платёж {formatMoney(transaction.amount_minor)} от {dateLabel(transaction.date)}. Разбивку возьмите из банковской выписки; если её нет, оставьте поля пустыми.</p>
      <Field label="Кредит"><Select value={loanId} onChange={(event) => { setLoanId(event.target.value); setAlreadyReflected(true); setStrategy('') }}><option value="">Выберите кредит</option>{loans.filter((loan) => !loan.archived).map((loan) => <option key={loan.id} value={loan.id}>{loan.name}</option>)}</Select></Field>
      <Field label="В основной долг"><Input inputMode="decimal" value={principal} onChange={(event) => setPrincipal(event.target.value)} placeholder="Неизвестно" /></Field>
      <Field label="В проценты"><Input inputMode="decimal" value={interest} onChange={(event) => setInterest(event.target.value)} placeholder="Неизвестно" /></Field>
      <label className="import-confirm-option"><input type="checkbox" checked={alreadyReflected} disabled={selectedLoan?.schedule_mode !== 'auto'} onChange={(event) => setAlreadyReflected(event.target.checked)} /><span><strong>Платёж уже учтён в указанном остатке долга</strong><small>Оставьте включённым для старых платежей. Для ручного графика долг меняется при проведении строки графика.</small></span></label>
      {!alreadyReflected && <Field label="Пересчёт после платежа"><Select value={strategy} onChange={(event) => setStrategy(event.target.value)} disabled={selectedLoan?.schedule_mode !== 'auto'}><option value="">Без досрочного пересчёта</option><option value="reduce_term">Сократить срок</option><option value="reduce_payment">Уменьшить платёж</option></Select></Field>}
      {(inputError || link.isError) && <div className="form-alert" role="alert">{inputError || actionError(link.error)}</div>}
      <div className="form-actions"><Button variant="ghost" onClick={onClose}>Отмена</Button><Button onClick={submit} disabled={!loanId || link.isPending}>{link.isPending ? 'Связываем…' : 'Связать'}</Button></div>
    </div>
  </Modal>
}

const matchBaseSchema = z.object({
  transaction_id: z.string().min(1, 'Выберите операцию'),
  occurrence_month: z.string().regex(/^\d{4}-(0[1-9]|1[0-2])$/, 'Укажите месяц плана'),
  amount: z.string().min(1, 'Укажите сумму'),
  completed: z.boolean().default(false),
})
function matchSchemaFor(currency: string) { return matchBaseSchema.superRefine((values, context) => {
  try {
    if (parseMoney(values.amount, currency) <= 0) throw new Error()
  } catch {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ['amount'], message: 'Укажите сумму больше нуля' })
  }
}) }
type MatchValues = z.infer<typeof matchBaseSchema>
interface MatchSubmission { values: MatchValues; idempotencyKey: string }

function planOccurrenceMonth(plan: PlanItem) {
  if (plan.recurrence !== 'none') return localDate().slice(0, 7)
  return plan.month ?? plan.date?.slice(0, 7) ?? plan.start_date?.slice(0, 7) ?? localDate().slice(0, 7)
}

function PlanMatchForm({ plan, onClose }: { plan: PlanItem; onClose: () => void }) {
  const currency = plan.currency ?? 'RUB'
  const client = useQueryClient()
  const submissionKey = useRef<string | null>(null)
  const transactions = useQuery<Transaction[] | ListResponse<Transaction>>({
    queryKey: ['/transactions', 'unmatched', plan.kind, currency],
    queryFn: () => api('/transactions?limit=500&offset=0'),
  })
  const facts = asList(transactions.data).filter((transaction) => transaction.type === plan.kind
    && (transaction.account_currency ?? 'RUB') === currency
    && transaction.matched_plan_item_id == null
    && !transaction.external_source?.startsWith('loan_schedule:'))
  const { register, handleSubmit, setValue, formState: { errors, isDirty } } = useForm<MatchValues>({
    resolver: zodResolver(matchSchemaFor(currency)),
    defaultValues: { transaction_id: '', occurrence_month: planOccurrenceMonth(plan), amount: '', completed: false },
  })
  const match = useMutation<unknown, Error, MatchSubmission>({
    mutationFn: ({ values, idempotencyKey }) => api(`/plan-items/${plan.id}/matches`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: jsonBody({
        transaction_id: Number(values.transaction_id),
        occurrence_month: values.occurrence_month,
        amount_minor: parseMoney(values.amount, currency),
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
          setValue('amount', moneyInput(Math.min(plan.amount_minor, fact.amount_minor), currency), { shouldDirty: true, shouldValidate: true })
          if (plan.recurrence !== 'none') setValue('occurrence_month', fact.date.slice(0, 7), { shouldDirty: true, shouldValidate: true })
        }
      }} autoFocus><option value="">Выберите факт</option>{facts.map((fact) => <option key={fact.id} value={fact.id}>{dateLabel(fact.date)} · {fact.description || 'Операция'} · {formatMoney(fact.amount_minor, currency)}</option>)}</Select></Field>
      <Field label="Месяц плана" error={errors.occurrence_month?.message}><Input type="month" {...register('occurrence_month')} /></Field>
      <Field label={`Сумма сверки, ${currency}`} error={errors.amount?.message}><Input inputMode="decimal" placeholder="0,00" {...register('amount')} /></Field>
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
  const scheduledPrincipal = items.reduce((sum, item) => sum + (item.status === 'cancelled' ? 0 : (item.principal_minor ?? 0)), 0)
  const scheduledInterest = items.reduce((sum, item) => sum + (item.status === 'cancelled' ? 0 : (item.interest_minor ?? 0)), 0)
  const scheduledTotal = items.reduce((sum, item) => sum + (item.status === 'cancelled' ? 0 : item.amount_minor), 0)
  const hasUnsaved = ((adding || Boolean(editingItem)) && isDirty) || Boolean(payingItem)
  const close = () => (!hasUnsaved || window.confirm('Закрыть график и потерять несохранённые данные?')) && onClose()
  const resetActions = () => { save.reset(); state.reset(); remove.reset() }
  const openNew = () => { resetActions(); reset({due_date:'',amount:'',principal:'',interest:''}); setEditingItem(null); setPayingItem(null); setAdding(true) }
  const openEdit = (item:LoanScheduleItem) => { resetActions(); reset({due_date:item.due_date,amount:moneyInput(item.amount_minor),principal:item.principal_minor==null?'':moneyInput(item.principal_minor),interest:item.interest_minor==null?'':moneyInput(item.interest_minor)}); setAdding(false); setPayingItem(null); setEditingItem(item) }
  const mutationError=actionError(save.error??state.error??remove.error)

  return <Modal title={`График кредита «${loan.name}»`} onClose={close}>
    <div className="schedule-summary"><div><span>Строк в графике</span><strong>{items.length}</strong></div><div><span>Остаток платежей</span><strong>{formatMoney(remaining)}</strong></div><Button variant="secondary" onClick={openNew} disabled={adding || Boolean(editingItem) || Boolean(payingItem)}><CirclePlus/> Добавить строку</Button></div>
    {(scheduledPrincipal > 0 || scheduledInterest > 0) && <div className="loan-projection-summary"><div><span>Плановый основной долг</span><strong>{formatMoney(scheduledPrincipal)}</strong></div><div><span>Плановая переплата по процентам</span><strong>{formatMoney(scheduledInterest)}</strong></div><div><span>Всего по графику</span><strong>{formatMoney(scheduledTotal)}</strong></div></div>}
    {(loan.paid_total_minor ?? 0) > 0 && <div className="loan-projection-summary"><div><span>Уже уплачено</span><strong>{formatMoney(loan.paid_total_minor ?? 0)}</strong></div><div><span>В основной долг</span><strong>{formatMoney(loan.paid_principal_minor ?? 0)}</strong></div><div><span>Известные проценты</span><strong>{formatMoney(loan.paid_interest_minor ?? 0)}</strong></div>{(loan.paid_unclassified_minor ?? 0) > 0 && <div><span>Без разбивки</span><strong>{formatMoney(loan.paid_unclassified_minor ?? 0)}</strong></div>}</div>}
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
