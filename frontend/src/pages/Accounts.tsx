import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowLeftRight, Banknote, Landmark, PiggyBank, WalletCards } from 'lucide-react'
import { api, asList } from '../lib/api'
import { dateLabel, formatMoney } from '../lib/format'
import type { Account, ListResponse } from '../lib/types'
import { Badge, Card, ErrorState, PageHeader, State } from '../components/ui'

type AccountView = Account & {
  type: 'bank' | 'cash' | 'savings'
  current_balance_minor: number
  initial_balance_minor: number
  initial_balance_date: string
  archived: boolean
}

const accountTypes = {
  bank: { label: 'Банковский счёт / карта', icon: Landmark },
  cash: { label: 'Наличные', icon: Banknote },
  savings: { label: 'Накопительный счёт', icon: PiggyBank },
}

function AccountCard({ account }: { account: AccountView }) {
  const accountType = accountTypes[account.type] ?? accountTypes.bank
  const Icon = accountType.icon
  return <Card className="account-card">
    <div className="account-card-head"><div className="account-card-icon"><Icon/></div><Badge tone={account.archived ? 'neutral' : 'good'}>{account.archived ? 'Архив' : 'Активен'}</Badge></div>
    <span className="eyebrow">{accountType.label}</span>
    <h3>{account.name}</h3>
    <strong className={account.current_balance_minor < 0 ? 'negative' : ''}>{formatMoney(account.current_balance_minor)}</strong>
    <div className="account-card-foot"><span>Начальный остаток на {dateLabel(account.initial_balance_date)}</span><b>{formatMoney(account.initial_balance_minor)}</b></div>
  </Card>
}

export function AccountsPage() {
  const accounts = useQuery<AccountView[] | ListResponse<AccountView>>({
    queryKey: ['accounts', { include_archived: true }],
    queryFn: () => api('/accounts?include_archived=true'),
  })
  const all = asList(accounts.data)
  const active = all.filter((account) => !account.archived)
  const archived = all.filter((account) => account.archived)
  const total = all.reduce((sum, account) => sum + account.current_balance_minor, 0)
  const activeTotal = active.reduce((sum, account) => sum + account.current_balance_minor, 0)
  const archivedTotal = total - activeTotal

  return <div className="page">
    <PageHeader eyebrow="Деньги" title="Счета" description="Остатки по счетам с учётом операций и внутренних переводов." actions={<><Link className="button button--secondary" to="/transactions"><ArrowLeftRight/> Операции и переводы</Link><Link className="button button--primary" to="/settings?tab=accounts"><WalletCards/> Управлять счетами</Link></>}/>
    {accounts.isLoading && <State kind="loading" title="Загружаем счета"/>}
    {accounts.isError && <ErrorState error={accounts.error} retry={() => accounts.refetch()}/>}
    {accounts.data && !all.length && <Card><State title="Счетов пока нет" action={<Link className="button button--primary" to="/settings?tab=accounts">Добавить счёт</Link>}>Создайте счёт и укажите начальный остаток.</State></Card>}
    {all.length > 0 && <>
      <div className="accounts-summary">
        <Card><span>На всех счетах</span><strong className={total < 0 ? 'negative' : ''}>{formatMoney(total)}</strong><small>{all.length} {all.length === 1 ? 'счёт' : 'счетов'} в учёте</small></Card>
        <Card><span>Активные счета</span><strong className={activeTotal < 0 ? 'negative' : ''}>{formatMoney(activeTotal)}</strong><small>Активных счетов: {active.length}</small></Card>
        <Card><span>Счета в архиве</span><strong className={archivedTotal < 0 ? 'negative' : ''}>{formatMoney(archivedTotal)}</strong><small>Архивных счетов: {archived.length}</small></Card>
      </div>
      <section className="accounts-section"><div className="section-head"><div><span className="eyebrow">Доступные</span><h2>Активные счета</h2></div></div>{active.length ? <div className="account-grid">{active.map((account) => <AccountCard key={account.id} account={account}/>)}</div> : <State title="Активных счетов нет"/>}</section>
      {archived.length > 0 && <section className="accounts-section"><div className="section-head"><div><span className="eyebrow">История</span><h2>Архивные счета</h2></div></div><p className="form-hint">Остатки архивных счетов входят в общий итог.</p><div className="account-grid">{archived.map((account) => <AccountCard key={account.id} account={account}/>)}</div></section>}
    </>}
  </div>
}
