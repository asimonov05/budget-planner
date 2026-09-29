import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ChevronLeft, ChevronRight } from 'lucide-react'
import { ApiError, api, asList, jsonBody, queryString } from '../lib/api'
import { currentMonth, dateLabel, formatMoney, monthLabel, parseMoney } from '../lib/format'
import type { ID, ListResponse } from '../lib/types'
import { Badge, Button, ErrorState, Field, Input, Modal, PageHeader, State } from '../components/ui'

interface CalendarItem {
  id: ID
  title: string
  kind: 'income' | 'expense'
  amount_minor: number
  base_amount_minor?: number
  date: string | null
  base_date?: string | null
  occurrence_month: string
  account_id?: ID | null
  recurrence?: string
  has_override?: boolean
  version?: number
}

function shift(month: string, delta: number) {
  const [year, monthNumber] = month.split('-').map(Number)
  const result = new Date(year, monthNumber - 1 + delta, 1)
  return `${result.getFullYear()}-${String(result.getMonth() + 1).padStart(2, '0')}`
}

function moneyInput(minor: number) {
  return (minor / 100).toFixed(2).replace('.', ',')
}

function CalendarOccurrenceEditor({
  item,
  onClose,
  onSaved,
}: {
  item: CalendarItem
  onClose: () => void
  onSaved: (month: string) => void
}) {
  const client = useQueryClient()
  const [amount, setAmount] = useState(moneyInput(item.amount_minor))
  const [date, setDate] = useState(item.date ?? '')
  const [inputError, setInputError] = useState('')
  const baseAmount = item.base_amount_minor ?? item.amount_minor
  const baseDate = item.base_date ?? null
  const dirty = amount !== moneyInput(item.amount_minor) || date !== (item.date ?? '')
  const close = () => {
    if (!dirty || window.confirm('Закрыть и потерять несохранённые изменения?')) onClose()
  }
  const save = useMutation<unknown, Error, { amount_minor: number | null; moved_date: string | null; targetMonth: string }>({
    mutationFn: ({ amount_minor, moved_date }) => api(
      `/plan-items/${item.id}/overrides/${item.occurrence_month}`,
      { method: 'PUT', body: jsonBody({ amount_minor, moved_date, cancelled: false, version: item.version }) },
    ),
    onSuccess: async (_value, { targetMonth }) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['calendar'] }),
        client.invalidateQueries({ queryKey: ['/plan-items'] }),
        client.invalidateQueries({ queryKey: ['plan-items'] }),
        client.invalidateQueries({ queryKey: ['forecast'] }),
        client.invalidateQueries({ queryKey: ['analytics'] }),
      ])
      onSaved(targetMonth)
    },
  })
  const saveError = saveErrorMessage(save.error)

  const submit = () => {
    try {
      const amountMinor = parseMoney(amount)
      if (amountMinor < 0) {
        setInputError('Сумма не может быть отрицательной')
        return
      }
      if (baseDate && !date) {
        setInputError('Укажите дату поступления или платежа')
        return
      }
      setInputError('')
      save.mutate({
        amount_minor: amountMinor === baseAmount ? null : amountMinor,
        moved_date: date && date !== baseDate ? date : null,
        targetMonth: date ? date.slice(0, 7) : item.occurrence_month,
      })
    } catch (error) {
      setInputError(error instanceof Error ? error.message : 'Проверьте сумму')
    }
  }

  const restore = () => {
    setInputError('')
    save.mutate({
      amount_minor: null,
      moved_date: null,
      targetMonth: baseDate?.slice(0, 7) ?? item.occurrence_month,
    })
  }

  return <Modal title={`Изменить «${item.title}»`} onClose={close}>
    <form className="form-stack" onSubmit={(event) => { event.preventDefault(); submit() }}>
      <p className="form-hint">{item.recurrence && item.recurrence !== 'none'
        ? `Меняется только повторение за ${monthLabel(item.occurrence_month)}. Остальная серия сохранится.`
        : 'Меняется только эта запись.'}</p>
      <Badge tone={item.kind === 'income' ? 'good' : 'info'}>{item.kind === 'income' ? 'Доход' : 'Платёж'}</Badge>
      <Field label="Сумма" hint={`По серии: ${formatMoney(baseAmount)}`}><Input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} autoFocus /></Field>
      <Field label="Дата" hint={baseDate ? `По серии: ${dateLabel(baseDate)}` : 'Можно оставить без точной даты'}><Input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></Field>
      {(inputError || save.isError) && <div className="form-alert" role="alert">{inputError || saveError}</div>}
      <div className="form-actions">
        {item.has_override && <Button type="button" variant="secondary" onClick={restore} disabled={save.isPending}>Вернуть по серии</Button>}
        <Button type="button" variant="ghost" onClick={close}>Отмена</Button>
        <Button type="submit" disabled={save.isPending}>{save.isPending ? 'Сохраняем…' : 'Сохранить дату'}</Button>
      </div>
    </form>
  </Modal>
}

function saveErrorMessage(error: Error | null) {
  if (error instanceof ApiError && error.status === 409 && error.message.startsWith('Version conflict')) {
    return 'Запись изменилась в другой вкладке. Закройте окно и откройте её заново.'
  }
  return error?.message
}

export function CalendarPage() {
  const [month, setMonth] = useState(currentMonth())
  const [editing, setEditing] = useState<CalendarItem | null>(null)
  const query = useQuery<CalendarItem[] | ListResponse<CalendarItem>>({
    queryKey: ['calendar', month],
    queryFn: () => api(`/plan-items?${queryString({ month })}`),
  })
  const days = useMemo<Array<number | null>>(() => {
    const [year, monthNumber] = month.split('-').map(Number)
    const first = new Date(year, monthNumber - 1, 1)
    const count = new Date(year, monthNumber, 0).getDate()
    return [
      ...Array<number | null>((first.getDay() + 6) % 7).fill(null),
      ...Array.from({ length: count }, (_, index) => index + 1),
    ]
  }, [month])
  const items = asList(query.data)
  const dated = items.filter((item) => item.date)
  const undated = items.filter((item) => !item.date)

  return <div className="page">
    <PageHeader eyebrow="По датам" title="Календарь" description="Нажмите на поступление или платёж, чтобы изменить сумму и дату одного повторения." actions={<div className="month-switch"><button aria-label="Предыдущий месяц" onClick={() => setMonth(shift(month, -1))}><ChevronLeft /></button><input aria-label="Месяц календаря" type="month" value={month} onChange={(event) => setMonth(event.target.value)} /><button aria-label="Следующий месяц" onClick={() => setMonth(shift(month, 1))}><ChevronRight /></button></div>} />
    {query.isLoading && <State kind="loading" title="Составляем календарь" />}
    {query.isError && <ErrorState error={query.error} retry={() => query.refetch()} />}
    {query.data && <div className="calendar-layout">
      <div className="calendar"><div className="calendar-week">{['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((day) => <b key={day}>{day}</b>)}</div><div className="calendar-grid">{days.map((day, index) => <div className={`calendar-day ${day === new Date().getDate() && month === currentMonth() ? 'today' : ''}`} key={`${day}-${index}`}>{day && <><span>{day}</span>{dated.filter((item) => Number(item.date?.slice(-2)) === day).map((item) => <button type="button" className={`calendar-event calendar-event--${item.kind}`} key={`${item.id}-${item.occurrence_month}`} aria-label={`Изменить ${item.title} за ${monthLabel(item.occurrence_month)}`} onClick={() => setEditing(item)}><small>{item.title}{item.has_override ? ' · изменено' : ''}</small><b>{formatMoney(item.amount_minor)}</b></button>)}</>}</div>)}</div></div>
      <aside className="undated"><h2>Без точной даты</h2>{undated.length ? undated.map((item) => <button type="button" className="undated-item" key={`${item.id}-${item.occurrence_month}`} onClick={() => setEditing(item)}><span>{item.title}<small>{item.account_id ? 'Счёт выбран' : 'Счёт не выбран'}</small></span><b>{formatMoney(item.amount_minor)}</b></button>) : <State title="Все суммы распределены" />}{undated.length > 0 && <div className="notice"><AlertTriangle /><span>Дневной прогноз неполный</span></div>}</aside>
    </div>}
    {editing && <CalendarOccurrenceEditor key={`${editing.id}-${editing.occurrence_month}`} item={editing} onClose={() => setEditing(null)} onSaved={(targetMonth) => { setEditing(null); setMonth(targetMonth) }} />}
  </div>
}
