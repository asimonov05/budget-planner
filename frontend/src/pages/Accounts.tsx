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
type AccountList = ListResponse<AccountView> & { currency_display_mode?: 'separate' | 'converted'; base_currency?: string }
interface ConvertedTotal { currency: string; total_minor: number; as_of: string; rate_source: 'manual'; indicative: true }

const accountTypes = {
  bank: { label: 'Банковский счёт / карта', icon: Landmark },
  cash: { label: 'Наличные', icon: Banknote },
  savings: { label: 'Накопительный счёт', icon: PiggyBank },
}

function denomination(account: AccountView) { return account.currency ?? 'RUB' }

function AccountCard({ account }: { account: AccountView }) {
  const accountType = accountTypes[account.type] ?? accountTypes.bank
  const Icon = accountType.icon
  const currency = denomination(account)
  return <Card className="account-card">
    <div className="account-card-head"><div className="account-card-icon"><Icon/></div><Badge tone={account.archived ? 'neutral' : 'good'}>{account.archived ? 'Архив' : 'Активен'}</Badge></div>
    <span className="eyebrow">{accountType.label} · {currency}</span>
    <h3>{account.name}</h3>
    <strong className={account.current_balance_minor < 0 ? 'negative' : ''}>{formatMoney(account.current_balance_minor, currency)}</strong>
    <div className="account-card-foot"><span>Начальный остаток на {dateLabel(account.initial_balance_date)}</span><b>{formatMoney(account.initial_balance_minor, currency)}</b></div>
  </Card>
}

export function AccountsPage() {
  const accounts = useQuery<AccountView[] | AccountList>({
    queryKey: ['accounts', { include_archived: true }],
    queryFn: () => api('/accounts?include_archived=true'),
  })
  const all = asList(accounts.data)
  const displayMode = !Array.isArray(accounts.data) ? (accounts.data as AccountList | undefined)?.currency_display_mode ?? 'separate' : 'separate'
  const converted = useQuery<ConvertedTotal>({
    queryKey: ['accounts', 'converted-total'], queryFn: () => api('/accounts/converted-total'),
    enabled: displayMode === 'converted', retry: false,
  })
  const currencies = [...new Set(all.map(denomination))]
  const groups = currencies.map((currency) => {
    const items = all.filter((account) => denomination(account) === currency)
    const active = items.filter((account) => !account.archived)
    const archived = items.filter((account) => account.archived)
    return { currency, items, active, archived }
  })

  return <div className="page">
    <PageHeader eyebrow="Деньги" title="Счета" description={displayMode === 'converted' ? 'Общий ориентировочный итог и остатки по каждой валюте.' : 'Остатки и итоги отдельно по каждой валюте.'} actions={<><Link className="button button--secondary" to="/transactions"><ArrowLeftRight/> Операции и переводы</Link><Link className="button button--primary" to="/settings?tab=accounts"><WalletCards/> Управлять счетами</Link></>}/>
    {accounts.isLoading && <State kind="loading" title="Загружаем счета"/>}
    {accounts.isError && <ErrorState error={accounts.error} retry={() => accounts.refetch()}/>}
    {accounts.data && !all.length && <Card><State title="Счетов пока нет" action={<Link className="button button--primary" to="/settings?tab=accounts">Добавить счёт</Link>}>Создайте счёт и укажите начальный остаток.</State></Card>}
    {displayMode === 'converted' && converted.isLoading && <State kind="loading" title="Считаем общий итог"/>}
    {displayMode === 'converted' && converted.isError && <Card><State kind="error" title="Не хватает курсов для общего итога" action={<Link className="button button--primary" to="/settings?tab=currencies">Задать курсы</Link>}>{converted.error.message}</State></Card>}
    {displayMode === 'converted' && converted.data && <Card className="account-card"><span className="eyebrow">Ориентировочно всего</span><strong>{formatMoney(converted.data.total_minor, converted.data.currency)}</strong><small>По вручную заданным курсам. Остатки каждого счёта показаны ниже в собственной валюте.</small></Card>}
    {groups.map(({ currency, items, active, archived }) => {
      const total = items.reduce((sum, account) => sum + account.current_balance_minor, 0)
      const activeTotal = active.reduce((sum, account) => sum + account.current_balance_minor, 0)
      const archivedTotal = total - activeTotal
      return <section className="accounts-currency-group" key={currency}>
        <div className="section-head"><div><span className="eyebrow">Валюта счёта</span><h2>{currency}</h2></div></div>
        <div className="accounts-summary">
          <Card><span>На всех счетах</span><strong className={total < 0 ? 'negative' : ''}>{formatMoney(total, currency)}</strong><small>{items.length} {items.length === 1 ? 'счёт' : 'счетов'} в учёте</small></Card>
          <Card><span>Активные счета</span><strong className={activeTotal < 0 ? 'negative' : ''}>{formatMoney(activeTotal, currency)}</strong><small>Активных счетов: {active.length}</small></Card>
          <Card><span>Счета в архиве</span><strong className={archivedTotal < 0 ? 'negative' : ''}>{formatMoney(archivedTotal, currency)}</strong><small>Архивных счетов: {archived.length}</small></Card>
        </div>
        <section className="accounts-section"><div className="section-head"><div><h3>Активные счета</h3></div></div>{active.length ? <div className="account-grid">{active.map((account) => <AccountCard key={account.id} account={account}/>)}</div> : <State title="Активных счетов нет"/>}</section>
        {archived.length > 0 && <section className="accounts-section"><div className="section-head"><div><h3>Счета в архиве</h3></div></div><div className="account-grid">{archived.map((account) => <AccountCard key={account.id} account={account}/>)}</div></section>}
      </section>
    })}
  </div>
}
