import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowDownLeft, ArrowUpRight, ChevronLeft, ChevronRight, CircleDollarSign, Landmark, Lock, Target, Unlock } from 'lucide-react'
import { api, asList, queryString } from '../lib/api'
import { currentMonth, dateLabel, formatMoney, monthLabel } from '../lib/format'
import type { Account, Goal, ListResponse, Payment } from '../lib/types'
import { Badge, Button, Card, ErrorState, PageHeader, Progress, State } from '../components/ui'
import { BudgetCurrencyPicker } from '../components/BudgetCurrencyPicker'
import { useBudgetCurrency } from '../lib/useBudgetCurrency'

interface ForecastMonth { month: string; c_start: number; r_start: number; f_start: number; income: number; expense: number; goal_allocations: number; goal_releases: number; goal_expenses: number; goal_refunds: number; adjustments: number; c_end: number; r_end: number; f_end: number; incomplete: boolean; closed: boolean }
interface Forecast { currency: string; months: ForecastMonth[]; indicative?: boolean }
interface PlanItemDto { id: string | number; title: string; amount_minor: number; currency?: string; date?: string; month?: string; occurrence_month?: string; kind: string; status: string; account_id?: string | number }

function shiftMonth(month: string, delta: number) { const [y, m] = month.split('-').map(Number); const date = new Date(y, m - 1 + delta, 1); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}` }

export function DashboardPage() {
  const [month, setMonth] = useState(currentMonth())
  const [includePossible, setIncludePossible] = useState(false)
  const { currency, setCurrency, baseCurrency, displayMode, combined } = useBudgetCurrency()
  const client = useQueryClient()
  const forecast = useQuery<Forecast>({ queryKey: ['forecast', month, 1, includePossible, currency, combined], queryFn: () => api(combined
    ? `/forecast/converted?${queryString({ from_month: month, months: 1, include_possible: includePossible })}`
    : `/forecast?${queryString({ from_month: month, months: 1, include_possible: includePossible, currency })}`) })
  const accounts = useQuery<Account[] | ListResponse<Account>>({ queryKey: ['accounts'], queryFn: () => api('/accounts') })
  const goals = useQuery<Goal[] | ListResponse<Goal>>({ queryKey: ['goals'], queryFn: () => api('/goals') })
  const planItems = useQuery<PlanItemDto[] | ListResponse<PlanItemDto>>({ queryKey: ['plan-items', month], queryFn: () => api(`/plan-items?${queryString({ month })}`) })
  const data = forecast.data?.months[0]
  const upcoming = useMemo(() => asList(planItems.data).filter((x) => x.kind === 'expense' && x.status === 'planned' && (combined || (x.currency ?? baseCurrency) === currency)).sort((a, b) => (a.date ?? '').localeCompare(b.date ?? '')).slice(0, 5), [planItems.data, currency, combined, baseCurrency])
  const selectedAccounts = asList(accounts.data).filter((account) => (account.currency ?? 'RUB') === currency)
  const money = (amount?: number) => formatMoney(amount, currency)
  const isLoading = forecast.isLoading || accounts.isLoading || goals.isLoading
  const monthAction = useMutation({
    mutationFn: ({ targetMonth, action }: { targetMonth: string; action: 'close' | 'reopen' }) => api<{ month: string; status: string }>(`/months/${targetMonth}/${action}`, { method: 'POST' }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['forecast'] }) },
  })
  const selectMonth = (value: string) => { monthAction.reset(); setMonth(value) }
  const changeMonthStatus = () => {
    if (!data) return
    const action = data.closed ? 'reopen' : 'close'
    if (action === 'close' && !window.confirm(`Закрыть ${monthLabel(month)}? Финансовые изменения в этом месяце будут заблокированы до переоткрытия.`)) return
    monthAction.mutate({ targetMonth: month, action })
  }
  return <div className="page">
    <PageHeader eyebrow="Сводка" title={monthLabel(month)} description={combined ? `Общий ориентировочный итог в ${baseCurrency}.` : `Баланс, план и платежи отдельно в ${currency}.`} actions={<div className="dashboard-actions">
      <BudgetCurrencyPicker value={combined ? 'ALL' : currency} onChange={setCurrency} combinedAvailable={displayMode === 'converted'} baseCurrency={baseCurrency}/>
      <Button variant="secondary" disabled={!data || monthAction.isPending} onClick={changeMonthStatus}>{data?.closed ? <Unlock/> : <Lock/>}{monthAction.isPending ? 'Сохраняем…' : data?.closed ? 'Переоткрыть месяц' : 'Закрыть месяц'}</Button>
      <div className="month-switch"><button onClick={() => selectMonth(shiftMonth(month, -1))} aria-label="Предыдущий месяц"><ChevronLeft/></button><input type="month" aria-label="Выбранный месяц" value={month} onChange={(e) => selectMonth(e.target.value)} /><button onClick={() => selectMonth(shiftMonth(month, 1))} aria-label="Следующий месяц"><ChevronRight/></button></div>
    </div>} />
    <label className="toggle-row"><input type="checkbox" checked={includePossible} onChange={(e) => setIncludePossible(e.target.checked)} /><span>Учитывать возможные доходы</span></label>
    {monthAction.isError && <div className="form-alert month-action-error">{monthAction.error.message}</div>}
    {isLoading && <State kind="loading" title="Считаем прогноз" />}
    {forecast.isError && <ErrorState error={forecast.error} retry={() => forecast.refetch()} />}
    {combined && forecast.isError && <Link className="button button--secondary" to="/settings?tab=currencies">Проверить курсы в настройках</Link>}
    {combined && forecast.data && <div className="notice notice--calm">Общий итог рассчитан по курсам, заданным вручную в настройках. Эти же курсы применяются ко всем месяцам прогноза; суммы на счетах сохраняются в их валютах.</div>}
    {forecast.data && !data && <Card><State title={`Нет счетов в ${currency}`} action={<Link className="button button--primary" to="/settings?tab=accounts">Добавить счёт</Link>}>Выберите валюту другого счёта или добавьте новый.</State></Card>}
    {data && <>
      {data.closed && <div className="notice notice--calm"><Lock/><div><strong>Месяц закрыт</strong><span>В прогнозе зафиксирован факт. Переоткройте месяц, чтобы изменять финансовые данные.</span></div></div>}
      {data.incomplete && <div className="notice"><AlertTriangle/><div><strong>Дневной прогноз неполный</strong><span>У части плана нет точной даты или счёта. Месячные итоги рассчитаны полностью.</span></div></div>}
      {data.f_end < 0 && <div className="notice notice--danger"><AlertTriangle/><div><strong>В конце месяца не хватает {money(Math.abs(data.f_end))}</strong><span>Проверьте обязательные платежи или скорректируйте план.</span></div></div>}
      <div className="metric-grid">
        <Card className="metric metric--hero"><div className="metric-icon"><CircleDollarSign/></div><div className="metric-label">Свободно сейчас</div><strong>{money(data.f_start)}</strong><span>Деньги вне целевых резервов</span><div className="metric-divider"/><div className="metric-row"><span>Прогноз на конец месяца</span><b className={data.f_end < 0 ? 'negative' : ''}>{money(data.f_end)}</b></div></Card>
        <Card className="metric"><div className="metric-head"><span>Деньги на счетах</span><Landmark/></div><strong>{money(data.c_start)}</strong><span>{combined ? `Оценка в ${baseCurrency}` : `Остаток счетов в ${currency}`}</span><div className="mini-list">{(combined ? asList(accounts.data) : selectedAccounts).slice(0, 3).map((a) => <div key={a.id}><span>{a.name}</span><b>{formatMoney(a.balance_minor ?? (a as Account & { current_balance_minor?: number }).current_balance_minor, a.currency ?? baseCurrency)}</b></div>)}</div></Card>
        {currency === baseCurrency && <Card className="metric"><div className="metric-head"><span>В резервах целей</span><Target/></div><strong>{money(data.r_start)}</strong><span>{asList(goals.data).filter((g) => g.status !== 'archived').length} активных целей</span><div className="mini-list">{asList(goals.data).slice(0, 2).map((g) => <div key={g.id}><span>{g.name}</span><b>{money(g.reserved_minor)}</b></div>)}</div></Card>}
      </div>
      <div className="two-column">
        <Card><div className="section-head"><div><span className="eyebrow">План месяца</span><h2>Доходы и расходы</h2></div></div><div className="cashflow-bars"><div><div className="cashflow-label"><span><ArrowDownLeft className="positive"/>Доходы</span><b>{money(data.income)}</b></div><Progress value={data.income} max={Math.max(data.income, data.expense, 1)} tone="var(--positive)" /></div><div><div className="cashflow-label"><span><ArrowUpRight className="negative"/>Расходы</span><b>{money(data.expense)}</b></div><Progress value={data.expense} max={Math.max(data.income, data.expense, 1)} tone="var(--negative)" /></div><div><div className="cashflow-label"><span><Target/>Пополнения целей</span><b>{money(data.goal_allocations)}</b></div><Progress value={data.goal_allocations} max={Math.max(data.income, data.expense, 1)} tone="var(--blue)" /></div></div><div className="summary-strip"><span>Изменение свободных денег</span><strong className={data.f_end - data.f_start < 0 ? 'negative' : 'positive'}>{money(data.f_end - data.f_start)}</strong></div></Card>
        <Card><div className="section-head"><div><span className="eyebrow">На очереди</span><h2>Ближайшие платежи</h2></div><a href="/calendar">В календарь</a></div>{planItems.isLoading ? <State kind="loading" title="Загружаем платежи"/> : upcoming.length ? <div className="upcoming-list">{upcoming.map((item) => <div className="upcoming" key={`${item.id}-${item.occurrence_month ?? item.month ?? item.date ?? ''}`}><div className="date-tile"><b>{item.date ? new Date(`${item.date}T00:00:00`).getDate() : '—'}</b><span>{item.date ? new Intl.DateTimeFormat('ru-RU', { month: 'short' }).format(new Date(`${item.date}T00:00:00`)) : 'месяц'}</span></div><div><strong>{item.title}</strong><span>{dateLabel(item.date)} · {item.account_id ? 'Счёт выбран' : 'Счёт не выбран'}</span></div><b>{formatMoney(item.amount_minor, item.currency ?? baseCurrency)}</b></div>)}</div> : <State title="Нет ближайших платежей">Добавьте обязательство в разделе «Платежи».</State>}</Card>
      </div>
    </>}
  </div>
}
