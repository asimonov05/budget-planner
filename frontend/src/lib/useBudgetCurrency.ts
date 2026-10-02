import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { Account, ListResponse } from './types'

type AccountList = ListResponse<Account> & { base_currency?: string }

export function useBudgetCurrency() {
  const accounts = useQuery<Account[] | AccountList>({
    queryKey: ['accounts', { include_archived: true }],
    queryFn: () => api('/accounts?include_archived=true'),
  })
  const baseCurrency = !Array.isArray(accounts.data) ? (accounts.data as AccountList | undefined)?.base_currency ?? 'RUB' : 'RUB'
  const [selectedCurrency, setCurrency] = useState<string | null>(null)
  return { currency: selectedCurrency ?? baseCurrency, setCurrency, baseCurrency }
}
