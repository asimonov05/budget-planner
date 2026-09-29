import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, CirclePlus, Pencil, RotateCcw, Trash2 } from 'lucide-react'
import { api, asList, jsonBody, queryString } from '../lib/api'
import { formatMoney, parseMoney, todayISO } from '../lib/format'
import type { Account, Category, ListResponse, Transaction } from '../lib/types'
import { Badge, Button, Card, Field, Input, Modal, Select, State } from './ui'

interface SalaryRule {
  id: number; name: string; gross_minor: number; advance_share_bps: number; advance_day: number;
  salary_day: number; start_month: string; end_month: string | null;
  initial_tax_base_minor: number; initial_tax_year: number | null;
  account_id: number; category_id: number | null; archived: boolean; version: number
}
interface SalaryPayment {
  salary_rule_id: number; employer: string; earning_month: string; component: 'advance' | 'salary';
  nominal_date: string; date: string; gross_minor: number; tax_minor: number; net_minor: number;
  matched_minor: number; remaining_minor: number; account_id: number; calendar_confirmed: boolean; tax_policy_confirmed: boolean
  matches: Array<{ id: number; transaction_id: number; amount_minor: number }>
}
interface Draft {
  name: string; gross: string; advancePercent: string; advanceDay: string; salaryDay: string;
  startMonth: string; endMonth: string; initialBase: string; accountId: string; categoryId: string
}
function monthNow() { return todayISO().slice(0, 7) }
function monthEnd(month: string) { const [year, number] = month.split('-').map(Number); return `${month}-${String(new Date(year, number, 0).getDate()).padStart(2, '0')}` }
function inputMoney(minor: number) { return (minor / 100).toFixed(2).replace('.', ',') }
function fromRule(rule?: SalaryRule): Draft {
  return {
    name: rule?.name ?? '', gross: rule ? inputMoney(rule.gross_minor) : '',
    advancePercent: rule ? String(rule.advance_share_bps / 100).replace('.', ',') : '40',
    advanceDay: String(rule?.advance_day ?? 25), salaryDay: String(rule?.salary_day ?? 10),
    startMonth: rule?.start_month ?? monthNow(), endMonth: rule?.end_month ?? '',
    initialBase: rule ? inputMoney(rule.initial_tax_base_minor) : '0',
    accountId: rule?.account_id ? String(rule.account_id) : '', categoryId: rule?.category_id ? String(rule.category_id) : '',
  }
}

export function SalarySettings() {
  const client = useQueryClient()
  const [editing, setEditing] = useState<SalaryRule | 'new' | null>(null)
  const [month, setMonth] = useState(monthNow())
  const [selectedReceipt, setSelectedReceipt] = useState<Record<string, string>>({})
  const settings = useQuery<{ salary_enabled: boolean; version: number }>({ queryKey: ['settings'], queryFn: () => api('/settings') })
  const rules = useQuery<ListResponse<SalaryRule>>({ queryKey: ['salary-rules'], queryFn: () => api('/salary-rules?include_archived=true') })
  const payments = useQuery<ListResponse<SalaryPayment>>({ queryKey: ['salary-payments', month], queryFn: () => api(`/salary-payments?${queryString({ month })}`), enabled: Boolean(settings.data?.salary_enabled) })
  const receipts = useQuery<ListResponse<Transaction>>({ queryKey: ['salary-receipts', month], queryFn: () => api(`/transactions?${queryString({ from_date: `${month}-01`, to_date: monthEnd(month), limit: 500 })}`), enabled: Boolean(settings.data?.salary_enabled) })
  const invalidate = async () => {
    await Promise.all([client.invalidateQueries({ queryKey: ['salary-rules'] }), client.invalidateQueries({ queryKey: ['salary-payments'] }), client.invalidateQueries({ queryKey: ['salary-receipts'] }), client.invalidateQueries({ queryKey: ['forecast'] }), client.invalidateQueries({ queryKey: ['analytics'] }), client.invalidateQueries({ queryKey: ['/transactions'] })])
  }
  const toggle = useMutation({ mutationFn: () => api('/settings', { method: 'PATCH', body: jsonBody({ version: settings.data?.version, salary_enabled: !settings.data?.salary_enabled }) }), onSuccess: async () => { await client.invalidateQueries({ queryKey: ['settings'] }); await invalidate() } })
  const state = useMutation({ mutationFn: ({ rule, archived }: { rule: SalaryRule; archived: boolean }) => api(`/salary-rules/${rule.id}`, { method: 'PUT', body: jsonBody({ ...rule, archived, version: rule.version }) }), onSuccess: invalidate })
  const remove = useMutation({ mutationFn: (rule: SalaryRule) => api(`/salary-rules/${rule.id}?${queryString({ version: rule.version })}`, { method: 'DELETE' }), onSuccess: invalidate })
  const match = useMutation({ mutationFn: ({ payment, transaction }: { payment: SalaryPayment; transaction: Transaction }) => api(`/salary-rules/${payment.salary_rule_id}/matches`, { method: 'POST', body: jsonBody({ earning_month: payment.earning_month, component: payment.component, transaction_id: transaction.id, amount_minor: Math.min(payment.remaining_minor, transaction.amount_minor) }) }), onSuccess: async (_result, { payment }) => { setSelectedReceipt((previous) => ({ ...previous, [keyFor(payment)]: '' })); await invalidate() } })
  const unmatch = useMutation({ mutationFn: (id: number) => api(`/salary-matches/${id}`, { method: 'DELETE' }), onSuccess: invalidate })
  const active = asList(rules.data).filter((item) => !item.archived)
  const keyFor = (payment: SalaryPayment) => `${payment.salary_rule_id}:${payment.earning_month}:${payment.component}`
  return <div className="form-stack">
    <Card className="settings-card"><div className="section-head"><div><span className="eyebrow">Зарплата</span><h2>Расчёт из суммы до налога</h2></div></div>
      <label className="import-confirm-option"><input type="checkbox" checked={Boolean(settings.data?.salary_enabled)} disabled={!settings.data || toggle.isPending} onChange={() => toggle.mutate()}/><span><strong>Учитывать зарплату до налога</strong><small>Каждый работодатель рассчитывается отдельно. В прогнозе и начислениях появятся аванс и зарплата после НДФЛ.</small></span></label>
      {toggle.isError && <div className="form-alert" role="alert">{toggle.error.message}</div>}
      <p>Если зарплата уже заведена как постоянный доход, вручную отключите старую запись на странице «Доходы», затем добавьте её здесь.</p>
      <p>Выплаты до даты начального остатка выбранного счёта не прибавляются к прогнозу. При расчёте НДФЛ они всё равно учитываются в доходе года.</p>
      <p>Расчёт: резидент РФ, прогрессивный НДФЛ без вычетов, налог с каждой выплаты. Работодатели удерживают налог отдельно; возможный итоговый перерасчёт ФНС между ними в прогноз не включён. Календарь подтверждён для 2025–2027 годов; налоговая шкала после 2026 года предварительная.</p>
    </Card>
    {settings.data?.salary_enabled && <>
      <Card className="settings-card"><div className="section-head"><div><span className="eyebrow">Работодатели</span><h2>Зарплатные правила</h2></div><Button onClick={() => setEditing('new')}><CirclePlus/> Добавить</Button></div>
        {rules.isLoading ? <State kind="loading" title="Загружаем зарплаты"/> : rules.isError ? <State kind="error" title="Не удалось загрузить зарплаты"/> : asList(rules.data).length ? <div className="directory-list">{asList(rules.data).map((rule) => <div key={rule.id}><div><strong>{rule.name}</strong><small>{formatMoney(rule.gross_minor)} до налога · аванс {rule.advance_share_bps / 100}% / зарплата {(10_000 - rule.advance_share_bps) / 100}% · {rule.start_month}{rule.end_month ? ` — ${rule.end_month}` : ''}</small></div>{rule.archived && <Badge>Архив</Badge>}<div className="directory-actions"><button className="icon-button" aria-label={`Изменить ${rule.name}`} onClick={() => setEditing(rule)}><Pencil/></button><button className="icon-button" aria-label={`${rule.archived ? 'Восстановить' : 'Архивировать'} ${rule.name}`} onClick={() => state.mutate({ rule, archived: !rule.archived })}>{rule.archived ? <RotateCcw/> : <Archive/>}</button><button className="icon-button icon-button--danger" aria-label={`Удалить ${rule.name}`} onClick={() => { if (window.confirm(`Удалить «${rule.name}»?`)) remove.mutate(rule) }}><Trash2/></button></div></div>)}</div> : <State title="Работодатели не добавлены"/>}
        {(state.isError || remove.isError) && <div className="form-alert" role="alert">{(state.error ?? remove.error)?.message}</div>}
      </Card>
      <Card className="settings-card"><div className="section-head"><div><span className="eyebrow">Начисления после налога</span><h2>Выплаты по датам</h2></div><Field label="Месяц"><Input type="month" value={month} onChange={(event) => setMonth(event.target.value)}/></Field></div>
        {payments.isLoading ? <State kind="loading" title="Считаем выплаты"/> : payments.isError ? <State kind="error" title="Не удалось рассчитать выплаты"/> : asList(payments.data).length ? <div className="directory-list">{asList(payments.data).map((payment) => {
          const key = keyFor(payment)
          const candidates = asList(receipts.data).filter((item) => item.type === 'income' && Number(item.account_id) === payment.account_id && !item.matched_plan_item_id && !item.matched_salary_rule_id && item.amount_minor > 0)
          const selected = candidates.find((item) => String(item.id) === selectedReceipt[key])
          return <div key={key}><div><strong>{payment.employer} · {payment.component === 'advance' ? 'Аванс' : 'Зарплата'} · {payment.date}</strong><small>Начислено {formatMoney(payment.gross_minor)} · НДФЛ {formatMoney(payment.tax_minor)} · к выплате {formatMoney(payment.net_minor)}{payment.matched_minor ? ` · учтено фактом ${formatMoney(payment.matched_minor)}` : ''}</small><small>За {payment.earning_month}{payment.date !== payment.nominal_date ? ` · перенос с ${payment.nominal_date}` : ''}{!payment.calendar_confirmed || !payment.tax_policy_confirmed ? ' · предварительный расчёт' : ''}</small>{payment.matches.map((item) => <small key={item.id}>Связь с операцией №{item.transaction_id} · {formatMoney(item.amount_minor)} <button type="button" onClick={() => unmatch.mutate(item.id)}>Снять связь</button></small>)}</div>{payment.remaining_minor > 0 && <div className="salary-match-control"><Select aria-label={`Факт для ${payment.employer} ${payment.component}`} value={selectedReceipt[key] ?? ''} onChange={(event) => setSelectedReceipt({ ...selectedReceipt, [key]: event.target.value })}><option value="">Связать с поступлением</option>{candidates.map((item) => <option key={item.id} value={item.id}>{item.date} · {item.description || 'Поступление'} · {formatMoney(item.amount_minor)}</option>)}</Select><Button variant="secondary" disabled={!selected || match.isPending} onClick={() => selected && match.mutate({ payment, transaction: selected })}>Связать</Button></div>}</div>
        })}</div> : <State title="В этом месяце выплат нет"/>}
        {(match.isError || unmatch.isError) && <div className="form-alert" role="alert">{(match.error ?? unmatch.error)?.message}</div>}
      </Card>
    </>}
    {editing && <SalaryRuleForm rule={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} onSaved={invalidate}/>}
    {active.some((rule) => rule.initial_tax_base_minor === 0 && rule.start_month > `${rule.start_month.slice(0, 4)}-01`) && settings.data?.salary_enabled && <p>Для зарплаты, заведённой в середине года, укажите уже начисленную у этого работодателя сумму с начала года: она влияет на прогрессивную ставку.</p>}
  </div>
}

function SalaryRuleForm({ rule, onClose, onSaved }: { rule?: SalaryRule; onClose: () => void; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState<Draft>(() => fromRule(rule))
  const accounts = useQuery<ListResponse<Account>>({ queryKey: ['accounts'], queryFn: () => api('/accounts') })
  const categories = useQuery<ListResponse<Category>>({ queryKey: ['income-categories'], queryFn: () => api('/categories?kind=income') })
  const save = useMutation({ mutationFn: async () => {
    const gross = parseMoney(draft.gross)
    const percentText = draft.advancePercent.trim().replace(',', '.')
    const share = Number(percentText)
    const shareBps = Math.round(share * 100)
    const opening = parseMoney(draft.initialBase || '0')
    if (!draft.name.trim() || gross <= 0 || !/^\d{1,2}(?:\.\d{1,2})?$/.test(percentText) || shareBps <= 0 || shareBps >= 10_000 || !draft.accountId) throw new Error('Проверьте работодателя, сумму, доли выплат и счёт')
    if (draft.endMonth && draft.endMonth < draft.startMonth) throw new Error('Конец периода раньше начала')
    const body = { name: draft.name.trim(), gross_minor: gross, advance_share_bps: shareBps, advance_day: Number(draft.advanceDay), salary_day: Number(draft.salaryDay), start_month: draft.startMonth, end_month: draft.endMonth || null, initial_tax_base_minor: opening, initial_tax_year: opening > 0 ? Number(draft.startMonth.slice(0, 4)) : null, account_id: Number(draft.accountId), category_id: draft.categoryId ? Number(draft.categoryId) : null }
    return api(rule ? `/salary-rules/${rule.id}` : '/salary-rules', { method: rule ? 'PUT' : 'POST', body: jsonBody(rule ? { ...body, archived: rule.archived, version: rule.version } : body) })
  }, onSuccess: async () => { await onSaved(); onClose() } })
  const set = (field: keyof Draft, value: string) => setDraft({ ...draft, [field]: value })
  return <Modal title={rule ? `Зарплата: ${rule.name}` : 'Новая зарплата'} onClose={onClose}><div className="form-stack">
    <Field label="Работодатель"><Input autoFocus value={draft.name} onChange={(event) => set('name', event.target.value)}/></Field>
    <Field label="Зарплата за месяц до налога"><Input inputMode="decimal" value={draft.gross} onChange={(event) => set('gross', event.target.value)} placeholder="100000,00"/></Field>
    <div className="form-grid"><Field label="Аванс, %"><Input inputMode="decimal" value={draft.advancePercent} onChange={(event) => set('advancePercent', event.target.value)}/></Field><Field label="Зарплата, %"><Input value={Number.isFinite(Number(draft.advancePercent.replace(',', '.'))) ? String(100 - Number(draft.advancePercent.replace(',', '.'))) : ''} readOnly/></Field></div>
    <div className="form-grid"><Field label="Аванс: день текущего месяца"><Input type="number" min="16" max="31" value={draft.advanceDay} onChange={(event) => set('advanceDay', event.target.value)}/></Field><Field label="Зарплата: день следующего месяца"><Input type="number" min="1" max="15" value={draft.salaryDay} onChange={(event) => set('salaryDay', event.target.value)}/></Field></div>
    <div className="form-grid"><Field label="С какого месяца начислять"><Input type="month" value={draft.startMonth} onChange={(event) => set('startMonth', event.target.value)}/></Field><Field label="Последний месяц, необязательно"><Input type="month" value={draft.endMonth} onChange={(event) => set('endMonth', event.target.value)}/></Field></div>
    <Field label="Налоговая база до месяца начала правила" hint="До налога, у этого работодателя с начала года. Выплаты месяца начала здесь не учитывайте: правило рассчитает их само, даже если они раньше начального остатка счёта."><Input inputMode="decimal" value={draft.initialBase} onChange={(event) => set('initialBase', event.target.value)}/></Field>
    <Field label="Счёт поступления"><Select value={draft.accountId} onChange={(event) => set('accountId', event.target.value)}><option value="">Выберите счёт</option>{asList(accounts.data).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></Field>
    <Field label="Категория дохода"><Select value={draft.categoryId} onChange={(event) => set('categoryId', event.target.value)}><option value="">Без категории</option>{asList(categories.data).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></Field>
    {save.isError && <div className="form-alert" role="alert">{save.error.message}</div>}
    <div className="form-actions"><Button variant="ghost" onClick={onClose}>Отмена</Button><Button disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Сохраняем…' : 'Сохранить'}</Button></div>
  </div></Modal>
}
