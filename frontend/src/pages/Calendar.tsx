import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ChevronLeft, ChevronRight } from 'lucide-react'
import { api, asList, queryString } from '../lib/api'
import { currentMonth, formatMoney, monthLabel } from '../lib/format'
import type { ListResponse } from '../lib/types'
import { Badge, ErrorState, PageHeader, State } from '../components/ui'

interface Item { id: string | number; title: string; kind: string; amount_minor: number; date?: string; month?: string; account_id?: string | number; status: string }
function shift(month: string, delta: number) { const [y,m] = month.split('-').map(Number); const d = new Date(y,m-1+delta,1); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}` }

export function CalendarPage() {
  const [month, setMonth] = useState(currentMonth())
  const query = useQuery<Item[] | ListResponse<Item>>({ queryKey: ['calendar', month], queryFn: () => api(`/plan-items?${queryString({ month })}`) })
  const days = useMemo<Array<number | null>>(() => { const [y,m] = month.split('-').map(Number); const first = new Date(y,m-1,1); const count = new Date(y,m,0).getDate(); return [...Array<number | null>((first.getDay()+6)%7).fill(null), ...Array.from({ length: count }, (_,i) => i+1)] }, [month])
  const dated = asList(query.data).filter((x) => x.date); const undated = asList(query.data).filter((x) => !x.date)
  return <div className="page"><PageHeader eyebrow="По датам" title="Календарь" description="Известные даты поступлений и платежей. Недатированные суммы показаны отдельно." actions={<div className="month-switch"><button onClick={() => setMonth(shift(month,-1))}><ChevronLeft/></button><input type="month" value={month} onChange={(e) => setMonth(e.target.value)}/><button onClick={() => setMonth(shift(month,1))}><ChevronRight/></button></div>}/>
    {query.isLoading && <State kind="loading" title="Составляем календарь"/>}{query.isError && <ErrorState error={query.error} retry={() => query.refetch()}/>} {query.data && <div className="calendar-layout"><div className="calendar"><div className="calendar-week">{['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map((d) => <b key={d}>{d}</b>)}</div><div className="calendar-grid">{days.map((day,i) => <div className={`calendar-day ${day === new Date().getDate() && month === currentMonth() ? 'today' : ''}`} key={`${day}-${i}`}>{day && <><span>{day}</span>{dated.filter((x) => Number(x.date?.slice(-2)) === day).map((item) => <div className={`calendar-event calendar-event--${item.kind}`} key={item.id}><small>{item.title}</small><b>{formatMoney(item.amount_minor)}</b></div>)}</>}</div>)}</div></div><aside className="undated"><h2>Без точной даты</h2>{undated.length ? undated.map((item) => <div key={item.id}><span>{item.title}<small>{item.account_id ? 'Счёт выбран' : 'Счёт не выбран'}</small></span><b>{formatMoney(item.amount_minor)}</b></div>) : <State title="Все суммы распределены"/>}{undated.length > 0 && <div className="notice"><AlertTriangle/><span>Дневной прогноз неполный</span></div>}</aside></div>}
  </div>
}
