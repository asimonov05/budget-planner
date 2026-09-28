import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, asList, queryString } from '../lib/api'
import { dateLabel, formatMoney, parseMoney } from '../lib/format'
import type { ListResponse, Loan, Transaction } from '../lib/types'
import { Button, ErrorState, Field, Input, Modal, Select, State } from './ui'

interface ProjectionRow {
  due_date: string
  payment_minor: number
  interest_minor: number
  principal_minor: number
  remaining_principal_minor: number
  early_principal_minor: number
}

interface Projection {
  regular_payment_minor: number
  rows: ProjectionRow[]
  interest_minor: number
  principal_minor: number
  total_minor: number
  payoff_date: string | null
}

interface ProjectionResponse {
  baseline: Projection
  scenario?: Projection
  interest_savings_minor?: number
}

type EarlyStrategy = 'reduce_term' | 'reduce_payment'

export function AutoLoanProjection({ loan, onClose }: { loan: Loan; onClose: () => void }) {
  const [amount, setAmount] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [strategy, setStrategy] = useState<EarlyStrategy>('reduce_term')
  const [inputError, setInputError] = useState('')
  const baseline = useQuery<ProjectionResponse>({
    queryKey: ['/loans', loan.id, 'projection'],
    queryFn: () => api(`/loans/${loan.id}/projection`),
  })
  const payments = useQuery<Transaction[] | ListResponse<Transaction>>({
    queryKey: ['/transactions', { loan_id: loan.id }],
    queryFn: () => api(`/transactions?${queryString({ loan_id: loan.id, limit: 500, offset: 0 })}`),
  })
  const preview = useMutation<ProjectionResponse, Error, { amountMinor: number; date: string; strategy: EarlyStrategy }>({
    mutationFn: ({ amountMinor, date, strategy: selectedStrategy }) => api(
      `/loans/${loan.id}/projection?${queryString({ early_payment_date: date, early_amount_minor: amountMinor, early_strategy: selectedStrategy })}`,
    ),
  })
  const projection = preview.data?.scenario ?? baseline.data?.baseline
  const selectedRow = baseline.data?.baseline.rows.find((row) => row.due_date === dueDate)

  const calculate = () => {
    try {
      const amountMinor = parseMoney(amount)
      if (!dueDate || amountMinor <= 0 || !selectedRow || amountMinor > selectedRow.remaining_principal_minor) {
        setInputError('Выберите дату платежа и сумму не больше остатка долга после него')
        return
      }
      setInputError('')
      preview.mutate({ amountMinor, date: dueDate, strategy })
    } catch {
      setInputError('Укажите положительную сумму досрочного погашения')
    }
  }

  return <Modal title={`Расчёт кредита «${loan.name}»`} onClose={onClose}>
    <p className="form-hint">Расчёт по годовой ставке и фактическому числу дней. {loan.interest_method === 'compound' ? 'Сложные проценты капитализируются ежедневно.' : 'Простые проценты начисляются на остаток основного долга.'} Сверяйте прогноз с графиком банка.</p>
    {(loan.paid_total_minor ?? 0) > 0 && <div className="loan-projection-summary"><div><span>Уже уплачено</span><strong>{formatMoney(loan.paid_total_minor ?? 0)}</strong></div><div><span>В основной долг</span><strong>{formatMoney(loan.paid_principal_minor ?? 0)}</strong></div><div><span>Известные проценты</span><strong>{formatMoney(loan.paid_interest_minor ?? 0)}</strong></div>{(loan.paid_unclassified_minor ?? 0) > 0 && <div><span>Без разбивки</span><strong>{formatMoney(loan.paid_unclassified_minor ?? 0)}</strong></div>}</div>}
    {baseline.isLoading && <State kind="loading" title="Рассчитываем график" />}
    {baseline.isError && <ErrorState error={baseline.error} retry={() => baseline.refetch()} />}
    {projection && <>
      <div className="loan-projection-summary">
        <div><span>Регулярный платёж</span><strong>{formatMoney(preview.data?.scenario?.rows.find((row) => row.due_date > dueDate)?.payment_minor ?? projection.regular_payment_minor)}</strong></div>
        <div><span>Будущие проценты</span><strong>{formatMoney(projection.interest_minor)}</strong></div>
        <div><span>Известная переплата по процентам</span><strong>{formatMoney((loan.paid_interest_minor ?? 0) + projection.interest_minor)}</strong></div>
        <div><span>Погашение долга</span><strong>{formatMoney(projection.principal_minor)}</strong></div>
        <div><span>Всего платежей</span><strong>{formatMoney(projection.total_minor)}</strong></div>
        <div><span>Дата погашения</span><strong>{projection.payoff_date ? dateLabel(projection.payoff_date) : '—'}</strong></div>
      </div>
      {preview.data?.scenario && <div className="notice notice--calm"><div><strong>Экономия на процентах: {formatMoney(preview.data.interest_savings_minor ?? 0)}</strong><span>{strategy === 'reduce_term' ? 'Размер регулярного платежа сохранён, срок сокращён.' : 'Конечная дата сохранена, регулярный платёж уменьшен.'}</span></div></div>}
      <div className="appearance-subsection"><span className="eyebrow">Сценарий</span><h3>Досрочное погашение</h3><p>Дополнительная сумма идёт в основной долг после обычного платежа в выбранную дату.</p></div>
      <div className="form-grid loan-early-form">
        <Field label="Дата по графику"><Select value={dueDate} onChange={(event) => { setDueDate(event.target.value); preview.reset() }}><option value="">Выберите дату</option>{baseline.data?.baseline.rows.filter((row) => row.remaining_principal_minor > 0).map((row) => <option key={row.due_date} value={row.due_date}>{dateLabel(row.due_date)} · осталось {formatMoney(row.remaining_principal_minor)}</option>)}</Select></Field>
        <Field label="Дополнительная сумма"><Input inputMode="decimal" value={amount} onChange={(event) => { setAmount(event.target.value); preview.reset() }} placeholder="0,00" /></Field>
        <Field label="Пересчёт"><Select value={strategy} onChange={(event) => { setStrategy(event.target.value as EarlyStrategy); preview.reset() }}><option value="reduce_term">Сократить срок</option><option value="reduce_payment">Уменьшить платёж</option></Select></Field>
        <div className="loan-early-actions"><Button type="button" onClick={calculate} disabled={preview.isPending}>Рассчитать</Button>{preview.data && <Button type="button" variant="ghost" onClick={() => preview.reset()}>Сбросить</Button>}</div>
      </div>
      {(inputError || preview.isError) && <div className="form-alert" role="alert">{inputError || preview.error?.message}</div>}
      <div className="loan-projection-table-wrap"><table className="loan-projection-table"><thead><tr><th>Дата</th><th>Платёж</th><th>Основной долг</th><th>Проценты</th><th>Остаток долга</th></tr></thead><tbody>{projection.rows.map((row) => <tr key={row.due_date}><td>{dateLabel(row.due_date)}</td><td>{formatMoney(row.payment_minor)}{row.early_principal_minor > 0 && <small>в том числе досрочно {formatMoney(row.early_principal_minor)}</small>}</td><td>{formatMoney(row.principal_minor)}</td><td>{formatMoney(row.interest_minor)}</td><td>{formatMoney(row.remaining_principal_minor)}</td></tr>)}</tbody></table></div>
      {asList(payments.data).length > 0 && <><div className="appearance-subsection"><span className="eyebrow">Факт</span><h3>Проведённые платежи</h3><p>Разбивка сохраняется вместе с каждой операцией.</p></div><div className="loan-projection-table-wrap"><table className="loan-projection-table"><thead><tr><th>Дата</th><th>Сумма</th><th>Основной долг</th><th>Проценты</th><th>Тип</th></tr></thead><tbody>{asList(payments.data).map((payment) => <tr key={payment.id}><td>{dateLabel(payment.date)}</td><td>{formatMoney(payment.amount_minor)}</td><td>{payment.principal_component_minor == null ? '—' : formatMoney(payment.principal_component_minor)}</td><td>{payment.interest_component_minor == null ? '—' : formatMoney(payment.interest_component_minor)}</td><td>{payment.prepayment_strategy === 'reduce_term' ? 'Досрочно · срок' : payment.prepayment_strategy === 'reduce_payment' ? 'Досрочно · платёж' : 'Обычный'}</td></tr>)}</tbody></table></div></>}
      <p className="form-hint">Фактический платёж добавьте в разделе «Операции», выбрав этот кредит. Для досрочного платежа укажите тот же вариант пересчёта.</p>
    </>}
  </Modal>
}
