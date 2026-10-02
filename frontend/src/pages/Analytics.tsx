import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, asList, queryString } from '../lib/api'
import { currencyDigits, currentMonth, formatMoney, monthLabel } from '../lib/format'
import type { Category, ListResponse } from '../lib/types'
import { Badge, ErrorState, PageHeader, State } from '../components/ui'
import { BudgetCurrencyPicker } from '../components/BudgetCurrencyPicker'
import { useBudgetCurrency } from '../lib/useBudgetCurrency'

interface CategoryDetail { category_id: string | number; forecast_minor: number | string }
interface Month { month: string; income: number; expense: number; c_end: number; r_end: number; f_end: number; category_details?: CategoryDetail[] }
interface Forecast { currency: string; months: Month[] }
const colors = Array.from({ length: 8 }, (_, index) => `var(--chart-${index + 1})`)
function minusMonths(month: string, amount: number) { const [y,m] = month.split('-').map(Number); const d = new Date(y,m-1-amount,1); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}` }

export function AnalyticsPage() {
  const [end, setEnd] = useState(currentMonth()); const [period, setPeriod] = useState<6|12|24>(12)
  const { currency, setCurrency, baseCurrency, displayMode, combined } = useBudgetCurrency()
  const scale = 10 ** currencyDigits(currency)
  const start = minusMonths(end, period - 1)
  const report = useQuery<Forecast>({ queryKey: ['analytics', start, period, currency, combined], queryFn: () => api(combined
    ? `/forecast/converted?${queryString({ from_month: start, months: period, include_possible: false })}`
    : `/forecast?${queryString({ from_month: start, months: period, include_possible: false, currency })}`) })
  const categoryQuery = useQuery<Category[] | ListResponse<Category>>({ queryKey: ['categories', 'all'], queryFn: () => api('/categories?include_archived=true') })
  const timeline = report.data?.months.map((m) => ({ ...m, label: monthLabel(m.month, true), incomeValue: m.income/scale, expenseValue: m.expense/scale, freeValue: m.f_end/scale, reserveValue: m.r_end/scale })) ?? []
  const categories = useMemo(() => {
    const names = new Map(asList(categoryQuery.data).map((category) => [String(category.id), category.name]))
    const totals = new Map<string, number>()
    for (const month of report.data?.months ?? []) {
      for (const detail of month.category_details ?? []) {
        const amount = Number(detail.forecast_minor)
        if (!Number.isFinite(amount)) continue
        const name = names.get(String(detail.category_id)) ?? `Категория #${detail.category_id}`
        totals.set(name, (totals.get(name) ?? 0) + amount)
      }
    }
    return [...totals].map(([name, minor]) => ({ name, value: minor / scale }))
      .sort((a, b) => b.value - a.value).slice(0, 8)
  }, [report.data, categoryQuery.data, scale])
  return <div className="page"><PageHeader eyebrow="Отчёты" title="Аналитика" description={combined ? `Ориентировочная динамика всех валют в ${baseCurrency}.` : `Динамика отдельно в ${currency}.`} actions={<div className="toolbar"><BudgetCurrencyPicker value={combined ? 'ALL' : currency} onChange={setCurrency} combinedAvailable={displayMode === 'converted'} baseCurrency={baseCurrency}/><input className="input" type="month" value={end} onChange={(e) => setEnd(e.target.value)}/><select className="input" value={period} onChange={(e) => setPeriod(Number(e.target.value) as 6|12|24)}><option value="6">6 месяцев</option><option value="12">12 месяцев</option><option value="24">24 месяца</option></select></div>}/>
    <div className="plan-options"><Badge tone="neutral">Переводы и выделение резервов исключены из потребительских расходов</Badge></div>
    {combined && report.isError && <a className="button button--secondary" href="/settings?tab=currencies">Проверить курсы в настройках</a>}
    {combined && report.data && <div className="notice notice--calm">Графики пересчитаны по курсам, заданным вручную в настройках. Для всех месяцев используются те же курсы.</div>}
    {report.isLoading && <State kind="loading" title="Готовим аналитику"/>}{report.isError && <ErrorState error={report.error} retry={() => report.refetch()}/>} {report.data && <><div className="chart-card"><div className="section-head"><div><span className="eyebrow">Движение</span><h2>Доходы и расходы</h2></div></div><ResponsiveContainer width="100%" height={320}><BarChart data={timeline} margin={{ top: 12, right: 12, left: 0, bottom: 0 }}><CartesianGrid vertical={false} stroke="var(--chart-grid)"/><XAxis dataKey="label" tickLine={false} axisLine={false}/><YAxis tickFormatter={(v) => `${Math.round(v/1000)} тыс.`} tickLine={false} axisLine={false} width={65}/><Tooltip formatter={(value) => formatMoney(Number(value)*scale, currency)} labelFormatter={(label) => String(label)}/><Legend/><Bar dataKey="incomeValue" name="Доходы" fill="var(--green)" radius={[5,5,0,0]}/><Bar dataKey="expenseValue" name="Расходы" fill="var(--coral)" radius={[5,5,0,0]}/></BarChart></ResponsiveContainer></div><div className="chart-grid"><div className="chart-card"><div className="section-head"><div><span className="eyebrow">Структура</span><h2>По категориям</h2></div></div>{categories.length ? <div className="pie-layout"><ResponsiveContainer width="100%" height={280}><PieChart><Pie data={categories} dataKey="value" nameKey="name" innerRadius={62} outerRadius={100} paddingAngle={2}>{categories.map((_,i) => <Cell key={i} fill={colors[i%colors.length]}/>)}</Pie><Tooltip formatter={(v) => formatMoney(Number(v)*scale, currency)}/></PieChart></ResponsiveContainer><div className="chart-legend">{categories.map((c,i) => <div key={c.name}><i style={{background: colors[i%colors.length]}}/><span>{c.name}</span><b>{formatMoney(c.value*scale, currency)}</b></div>)}</div></div> : <State title="Недостаточно данных"/>}</div><div className="chart-card"><div className="section-head"><div><span className="eyebrow">Остатки</span><h2>Свободно и в резервах</h2></div></div><ResponsiveContainer width="100%" height={300}><LineChart data={timeline}><CartesianGrid vertical={false} stroke="var(--chart-grid)"/><XAxis dataKey="label" tickLine={false} axisLine={false}/><YAxis tickFormatter={(v) => `${Math.round(v/1000)} тыс.`} tickLine={false} axisLine={false} width={65}/><Tooltip formatter={(v) => formatMoney(Number(v)*scale, currency)}/><Legend/><Line type="monotone" dataKey="freeValue" name="Свободно" stroke="var(--green)" strokeWidth={3} dot={false}/>{currency === baseCurrency && <Line type="monotone" dataKey="reserveValue" name="В резервах" stroke="var(--blue)" strokeWidth={3} dot={false}/> }</LineChart></ResponsiveContainer></div></div></>}
  </div>
}
