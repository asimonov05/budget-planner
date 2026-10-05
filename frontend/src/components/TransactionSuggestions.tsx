import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, queryString } from '../lib/api'
import { dateLabel, formatMoney } from '../lib/format'

export interface TransactionSuggestion {
  id: number
  description: string
  date: string
  account_id: number
  account_name?: string | null
  account_currency?: string | null
  category_id: number | null
  category_name?: string | null
  amount_minor: number
  merchant_currency: string | null
  merchant_amount_minor: number | null
  tag_ids: number[]
}

export function TransactionSuggestions({
  value, transactionType, accountId, accountCurrencies, onSelect,
}: {
  value: string
  transactionType: 'expense' | 'income' | 'refund'
  accountId?: string
  accountCurrencies: Map<string, string>
  onSelect: (suggestion: TransactionSuggestion) => void
}) {
  const [query, setQuery] = useState('')
  const [selectedTitle, setSelectedTitle] = useState<string | null>(null)
  const trimmed = value.trim()
  useEffect(() => {
    if (trimmed.length < 2) { setQuery(''); return }
    const timer = window.setTimeout(() => setQuery(trimmed), 250)
    return () => window.clearTimeout(timer)
  }, [trimmed])
  const suggestions = useQuery<{ items: TransactionSuggestion[] }>({
    queryKey: ['transaction-suggestions', transactionType, query, accountId],
    queryFn: () => api(`/transactions/suggestions?${queryString({ query, type: transactionType, account_id: accountId, limit: 5 })}`),
    enabled: query.length >= 2 && query === trimmed && selectedTitle !== trimmed,
    retry: false,
    staleTime: 60_000,
  })
  if (trimmed.length < 2 || selectedTitle === trimmed || query !== trimmed || !suggestions.data?.items.length) return null
  return <div className="transaction-suggestions form-span" role="region" aria-label="Похожие операции">
    <strong>Похожие операции</strong>
    <div className="transaction-suggestions__list">{suggestions.data.items.map((item) => {
      const currency = item.merchant_currency ?? item.account_currency ?? accountCurrencies.get(String(item.account_id)) ?? 'RUB'
      const amount = item.merchant_amount_minor ?? item.amount_minor
      return <button key={item.id} type="button" onClick={() => { setSelectedTitle(item.description.trim()); onSelect(item) }}>
        <span>{item.description}</span>
        <small>{formatMoney(amount, currency)} · {item.account_name ? `${item.account_name} · ` : ''}{item.category_name ? `${item.category_name} · ` : ''}{dateLabel(item.date)}</small>
      </button>
    })}</div>
    <small>Выбор заполнит название, счёт, категорию, теги и сумму. Проверьте значения перед сохранением.</small>
  </div>
}
