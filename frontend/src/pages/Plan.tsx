import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { Check, Pencil, X } from 'lucide-react'
import { api, asList, jsonBody, queryString } from '../lib/api'
import { currencyDigits, currentMonth, formatMoney, monthLabel, parseMoney } from '../lib/format'
import type { Category, ListResponse } from '../lib/types'
import { Badge, Button, ErrorState, PageHeader, State } from '../components/ui'
import { BudgetCurrencyPicker } from '../components/BudgetCurrencyPicker'
import { useBudgetCurrency } from '../lib/useBudgetCurrency'

interface ForecastMonth { month: string; income: number; expense: number; estimated_expense_minor: number; goal_allocations: number; c_end: number; r_end: number; f_end: number; incomplete: boolean; category_details?: Array<{ category_id: string | number; forecast_minor: number; estimated_monthly_minor?: number | null; estimated_from_months?: number; estimated_added_minor?: number }> }
interface Forecast { currency: string; months: ForecastMonth[] }
interface Row { id: string; label: string; kind: string; values: Record<string, number>; hints?: Record<string, string>; tone?: string }

function PlanCell({ value, month, row, currency, baseCurrency }: { value: number; month: string; row: Row; currency: string; baseCurrency: string }) {
  const [editing, setEditing] = useState(false); const [draft, setDraft] = useState(''); const client = useQueryClient()
  const save = useMutation({ mutationFn: () => api('/budget-limits/batch', { method: 'POST', body: jsonBody({ changes: [{ category_id: row.id.replace('category-', ''), month, amount_minor: parseMoney(draft, currency) }], scope: 'instance' }) }), onSuccess: () => { client.invalidateQueries({ queryKey: ['forecast'] }); setEditing(false) } })
  if (!row.id.startsWith('category-') || currency !== baseCurrency) return <span className="plan-value" title={row.id === 'estimated' ? 'Добавлено по среднему сверх факта и планов; входит в «Все расходы»' : undefined} aria-label={`${row.label}, ${monthLabel(month)}: ${formatMoney(value, currency)}`}>{formatMoney(value, currency)}</span>
  if (!editing) return <button className="plan-value" title={row.hints?.[month]} onClick={() => { setDraft(String(value / 10 ** currencyDigits(currency)).replace('.', ',')); setEditing(true) }} aria-label={`${row.label}, ${monthLabel(month)}: ${formatMoney(value, currency)}`}>{formatMoney(value, currency)}<Pencil/></button>
  return <div className="inline-edit"><input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') save.mutate(); if (e.key === 'Escape') setEditing(false) }} /><button onClick={() => save.mutate()} disabled={save.isPending}><Check/></button><button onClick={() => setEditing(false)}><X/></button></div>
}

export function PlanPage() {
  const [start, setStart] = useState(currentMonth()); const [horizon, setHorizon] = useState<12 | 24>(12); const [possible, setPossible] = useState(false); const { currency, setCurrency, baseCurrency, displayMode, combined } = useBudgetCurrency()
  const forecast = useQuery<Forecast>({ queryKey: ['forecast', start, horizon, possible, currency, combined], queryFn: () => api(combined
    ? `/forecast/converted?${queryString({ from_month: start, months: horizon, include_possible: possible })}`
    : `/forecast?${queryString({ from_month: start, months: horizon, include_possible: possible, currency })}`) })
  const categories = useQuery<Category[] | ListResponse<Category>>({ queryKey: ['categories', 'all'], queryFn: () => api('/categories?include_archived=true') })
  const rows = useMemo<Row[]>(() => {
    const months = forecast.data?.months ?? []; const categoryRows = new Map<string, Row>(); const names = new Map(asList(categories.data).map((category) => [String(category.id), category.name])); const monthly = new Set(asList(categories.data).filter((category) => category.monthly_estimate).map((category) => String(category.id)))
    months.forEach((m) => m.category_details?.forEach((c) => { const id = `category-${c.category_id}`; const label = names.get(String(c.category_id)) ?? `Категория #${c.category_id}`; const row: Row = categoryRows.get(id) ?? { id, label: monthly.has(String(c.category_id)) ? `${label} · оценка` : label, kind: 'category', values: {}, hints: {} }; row.values[m.month] = c.forecast_minor; if (monthly.has(String(c.category_id))) row.hints![m.month] = c.estimated_monthly_minor == null ? 'Нет завершённых месяцев для оценки' : `Среднее за ${c.estimated_from_months} мес.: ${formatMoney(c.estimated_monthly_minor, currency)}. Добавлено к прогнозу: ${formatMoney(c.estimated_added_minor ?? 0, currency)}`; categoryRows.set(id, row) }))
    return [
      { id: 'income', label: 'Доходы', kind: 'summary', tone: 'positive', values: Object.fromEntries(months.map((m) => [m.month, m.income])) },
      ...categoryRows.values(),
      { id: 'estimated', label: 'Примерные расходы', kind: 'estimate', values: Object.fromEntries(months.map((m) => [m.month, m.estimated_expense_minor ?? 0])) },
      { id: 'expense', label: 'Все расходы', kind: 'summary', tone: 'negative', values: Object.fromEntries(months.map((m) => [m.month, m.expense])) },
      { id: 'goals', label: 'Пополнения целей', kind: 'summary', values: Object.fromEntries(months.map((m) => [m.month, m.goal_allocations])) },
      { id: 'free', label: 'Свободно на конец', kind: 'total', values: Object.fromEntries(months.map((m) => [m.month, m.f_end])) },
    ]
  }, [forecast.data, categories.data, currency])
  const months = forecast.data?.months.map((m) => m.month) ?? []
  const columnHelper = createColumnHelper<Row>()
  const columns = useMemo(() => [columnHelper.accessor('label', { header: 'Статья', cell: (info) => <div className="plan-label"><span className={`row-dot row-dot--${info.row.original.kind}`} />{info.getValue()}</div> }), ...months.map((month) => columnHelper.display({ id: month, header: () => <span>{monthLabel(month, true)}<small>{month.split('-')[0]}</small></span>, cell: ({ row }) => <PlanCell value={row.original.values[month] ?? 0} month={month} row={row.original} currency={currency} baseCurrency={baseCurrency} /> }))], [months.join('|'), currency, baseCurrency]) // eslint-disable-line react-hooks/exhaustive-deps
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() })
  return <div className="page page--wide"><PageHeader eyebrow="Планирование" title="План на год" description={combined ? `Ориентировочный прогноз всех валют в ${baseCurrency}.` : `Прогноз отдельно в ${currency}.`} actions={<div className="toolbar"><BudgetCurrencyPicker value={combined ? 'ALL' : currency} onChange={setCurrency} combinedAvailable={displayMode === 'converted'} baseCurrency={baseCurrency}/><input className="input" type="month" value={start} onChange={(e) => setStart(e.target.value)}/><div className="segmented"><button className={horizon === 12 ? 'active' : ''} onClick={() => setHorizon(12)}>12 мес.</button><button className={horizon === 24 ? 'active' : ''} onClick={() => setHorizon(24)}>24 мес.</button></div></div>} />
    <div className="plan-options"><label><input type="checkbox" checked={possible} onChange={(e) => setPossible(e.target.checked)}/> Учитывать возможные доходы</label><Badge tone="info">Все суммы рассчитаны сервером</Badge></div>
    {forecast.isLoading && <State kind="loading" title="Строим план" />}{forecast.isError && <ErrorState error={forecast.error} retry={() => forecast.refetch()} />}
    {combined && forecast.isError && <a className="button button--secondary" href="/settings?tab=currencies">Проверить курсы в настройках</a>}
    {combined && forecast.data && <div className="notice notice--calm">Пересчёт выполнен по вручную заданным курсам из настроек. Для будущих месяцев применяются те же курсы.</div>}
    {forecast.data && months.length === 0 && <State title={`Нет счетов в ${currency}`}>Выберите другую валюту или добавьте счёт.</State>}
    {forecast.data && months.length > 0 && <div className="plan-table-wrap"><table className="plan-table"><thead>{table.getHeaderGroups().map((group) => <tr key={group.id}>{group.headers.map((header) => <th key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</th>)}</tr>)}</thead><tbody>{table.getRowModel().rows.map((row) => <tr key={row.id} className={`plan-row plan-row--${row.original.kind}`}>{row.getVisibleCells().map((cell) => <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>)}</tbody></table></div>}
    {forecast.data && <div className="table-footnote">Примерные траты входят в строку «Все расходы»: среднее по завершённым месяцам добавляется только сверх уже учтённых фактов, планов и лимитов. Категорию можно отметить в «Настройки → Категории».</div>}
    {forecast.data && months.some((month, i) => forecast.data!.months[i].incomplete) && <div className="table-footnote">Некоторые месяцы содержат суммы без точной даты или счёта — дневной прогноз для них неполный.</div>}
  </div>
}
