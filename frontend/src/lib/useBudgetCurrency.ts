import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { Account, ListResponse } from './types'

type AccountList = ListResponse<Account> & {
  base_currency?: string
  currency_display_mode?: 'separate' | 'converted'
}

export function useBudgetCurrency() {
  const accounts = useQuery<Account[] | AccountList>({
    queryKey: ['accounts', { include_archived: true }],
    queryFn: () => api('/accounts?include_archived=true'),
  })
  const baseCurrency = !Array.isArray(accounts.data) ? (accounts.data as AccountList | undefined)?.base_currency ?? 'RUB' : 'RUB'
  const displayMode = !Array.isArray(accounts.data) ? (accounts.data as AccountList | undefined)?.currency_display_mode ?? 'separate' : 'separate'
  const [selectedCurrency, setCurrency] = useState<string | null>(null)
  const combined = displayMode === 'converted' && (selectedCurrency === null || selectedCurrency === 'ALL')
  const currency = selectedCurrency && selectedCurrency !== 'ALL' ? selectedCurrency : baseCurrency
  return { currency, setCurrency, baseCurrency, displayMode, combined }
}
