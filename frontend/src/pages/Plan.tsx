import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { Check, Pencil, X } from 'lucide-react'
import { api, asList, jsonBody, queryString } from '../lib/api'
import { currentMonth, formatMoney, monthLabel, parseMoney } from '../lib/format'
import type { Category, ListResponse } from '../lib/types'
import { Badge, Button, ErrorState, PageHeader, State } from '../components/ui'

interface ForecastMonth { month: string; income: number; expense: number; goal_allocations: number; c_end: number; r_end: number; f_end: number; incomplete: boolean; category_details?: Array<{ category_id: string | number; forecast_minor: number }> }
interface Forecast { months: ForecastMonth[] }
interface Row { id: string; label: string; kind: string; values: Record<string, number>; tone?: string }

function PlanCell({ value, month, row }: { value: number; month: string; row: Row }) {
  const [editing, setEditing] = useState(false); const [draft, setDraft] = useState(''); const client = useQueryClient()
  const save = useMutation({ mutationFn: () => api('/budget-limits/batch', { method: 'POST', body: jsonBody({ changes: [{ category_id: row.id.replace('category-', ''), month, amount_minor: parseMoney(draft) }], scope: 'instance' }) }), onSuccess: () => { client.invalidateQueries({ queryKey: ['forecast'] }); setEditing(false) } })
  if (!editing || !row.id.startsWith('category-')) return <button className="plan-value" onClick={() => { if (row.id.startsWith('category-')) { setDraft(String(value / 100).replace('.', ',')); setEditing(true) } }} aria-label={`${row.label}, ${monthLabel(month)}: ${formatMoney(value)}`}>{formatMoney(value)}{row.id.startsWith('category-') && <Pencil/>}</button>
  return <div className="inline-edit"><input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') save.mutate(); if (e.key === 'Escape') setEditing(false) }} /><button onClick={() => save.mutate()} disabled={save.isPending}><Check/></button><button onClick={() => setEditing(false)}><X/></button></div>
}

export function PlanPage() {
  const [start, setStart] = useState(currentMonth()); const [horizon, setHorizon] = useState<12 | 24>(12); const [possible, setPossible] = useState(false)
  const forecast = useQuery<Forecast>({ queryKey: ['forecast', start, horizon, possible], queryFn: () => api(`/forecast?${queryString({ from_month: start, months: horizon, include_possible: possible })}`) })
  const categories = useQuery<Category[] | ListResponse<Category>>({ queryKey: ['categories', 'all'], queryFn: () => api('/categories?include_archived=true') })
  const rows = useMemo<Row[]>(() => {
    const months = forecast.data?.months ?? []; const categoryRows = new Map<string, Row>(); const names = new Map(asList(categories.data).map((category) => [String(category.id), category.name]))
    months.forEach((m) => m.category_details?.forEach((c) => { const id = `category-${c.category_id}`; const row = categoryRows.get(id) ?? { id, label: names.get(String(c.category_id)) ?? `Категория #${c.category_id}`, kind: 'category', values: {} }; row.values[m.month] = c.forecast_minor; categoryRows.set(id, row) }))
    return [
      { id: 'income', label: 'Доходы', kind: 'summary', tone: 'positive', values: Object.fromEntries(months.map((m) => [m.month, m.income])) },
      ...categoryRows.values(),
      { id: 'expense', label: 'Все расходы', kind: 'summary', tone: 'negative', values: Object.fromEntries(months.map((m) => [m.month, m.expense])) },
      { id: 'goals', label: 'Пополнения целей', kind: 'summary', values: Object.fromEntries(months.map((m) => [m.month, m.goal_allocations])) },
      { id: 'free', label: 'Свободно на конец', kind: 'total', values: Object.fromEntries(months.map((m) => [m.month, m.f_end])) },
    ]
  }, [forecast.data, categories.data])
  const months = forecast.data?.months.map((m) => m.month) ?? []
  const columnHelper = createColumnHelper<Row>()
  const columns = useMemo(() => [columnHelper.accessor('label', { header: 'Статья', cell: (info) => <div className="plan-label"><span className={`row-dot row-dot--${info.row.original.kind}`} />{info.getValue()}</div> }), ...months.map((month) => columnHelper.display({ id: month, header: () => <span>{monthLabel(month, true)}<small>{month.split('-')[0]}</small></span>, cell: ({ row }) => <PlanCell value={row.original.values[month] ?? 0} month={month} row={row.original} /> }))], [months.join('|')]) // eslint-disable-line react-hooks/exhaustive-deps
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() })
  return <div className="page page--wide"><PageHeader eyebrow="Планирование" title="План на год" description="Прогноз переносит остатки между месяцами. Нажмите на сумму категории, чтобы изменить лимит." actions={<div className="toolbar"><input className="input" type="month" value={start} onChange={(e) => setStart(e.target.value)}/><div className="segmented"><button className={horizon === 12 ? 'active' : ''} onClick={() => setHorizon(12)}>12 мес.</button><button className={horizon === 24 ? 'active' : ''} onClick={() => setHorizon(24)}>24 мес.</button></div></div>} />
    <div className="plan-options"><label><input type="checkbox" checked={possible} onChange={(e) => setPossible(e.target.checked)}/> Учитывать возможные доходы</label><Badge tone="info">Все суммы рассчитаны сервером</Badge></div>
    {forecast.isLoading && <State kind="loading" title="Строим план" />}{forecast.isError && <ErrorState error={forecast.error} retry={() => forecast.refetch()} />}
    {forecast.data && <div className="plan-table-wrap"><table className="plan-table"><thead>{table.getHeaderGroups().map((group) => <tr key={group.id}>{group.headers.map((header) => <th key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</th>)}</tr>)}</thead><tbody>{table.getRowModel().rows.map((row) => <tr key={row.id} className={`plan-row plan-row--${row.original.kind}`}>{row.getVisibleCells().map((cell) => <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>)}</tbody></table></div>}
    {forecast.data && months.some((month, i) => forecast.data!.months[i].incomplete) && <div className="table-footnote">Некоторые месяцы содержат суммы без точной даты или счёта — дневной прогноз для них неполный.</div>}
  </div>
}
