import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, asList, queryString } from '../lib/api'
import { currentMonth, formatMoney } from '../lib/format'
import type { ListResponse } from '../lib/types'
import { Card, State } from './ui'

interface Payment {
  salary_rule_id: number; employer: string; component: 'advance' | 'salary'; date: string;
  gross_minor: number; tax_minor: number; net_minor: number; matched_minor: number;
  calendar_confirmed: boolean; tax_policy_confirmed: boolean
}

export function SalaryIncomeSummary() {
  const month = currentMonth()
  const settings = useQuery<{ salary_enabled: boolean }>({ queryKey: ['settings'], queryFn: () => api('/settings') })
  const payments = useQuery<ListResponse<Payment>>({ queryKey: ['salary-payments', month], queryFn: () => api(`/salary-payments?${queryString({ month })}`), enabled: Boolean(settings.data?.salary_enabled) })
  if (settings.isLoading || settings.isError) return null
  return <Card className="salary-income-summary"><div className="section-head"><div><span className="eyebrow">Зарплата</span><h2>Начисления после налога · {month}</h2></div><Link className="button button--secondary" to="/settings?tab=salary">Настроить</Link></div>
    {!settings.data?.salary_enabled ? <p>Включите расчёт зарплаты до налога в настройках, чтобы видеть аванс и зарплату после НДФЛ.</p> : payments.isLoading ? <State kind="loading" title="Считаем зарплату"/> : payments.isError ? <State kind="error" title="Не удалось рассчитать зарплату"/> : asList(payments.data).length ? <div className="directory-list">{asList(payments.data).map((payment) => <div key={`${payment.salary_rule_id}-${payment.date}-${payment.component}`}><div><strong>{payment.employer} · {payment.component === 'advance' ? 'аванс' : 'зарплата'} · {payment.date}</strong><small>До налога {formatMoney(payment.gross_minor)} · НДФЛ {formatMoney(payment.tax_minor)}{payment.matched_minor ? ` · учтено фактом ${formatMoney(payment.matched_minor)}` : ''}{!payment.calendar_confirmed || !payment.tax_policy_confirmed ? ' · предварительно' : ''}</small></div><strong>{formatMoney(payment.net_minor)}</strong></div>)}</div> : <p>В этом месяце нет запланированных зарплатных выплат.</p>}
  </Card>
}
