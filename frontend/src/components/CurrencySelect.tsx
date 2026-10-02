import { useQuery } from '@tanstack/react-query'
import { api, asList } from '../lib/api'
import { fallbackCurrencies, type CurrencyOption } from '../lib/currency'
import { Select } from './ui'

export function CurrencySelect({ value, onChange, disabled, allOption, 'aria-label': ariaLabel, 'aria-describedby': ariaDescribedby, 'aria-invalid': ariaInvalid }: {
  value: string
  onChange: (currency: string) => void
  disabled?: boolean
  allOption?: string
  'aria-label'?: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean
}) {
  const currencies = useQuery<CurrencyOption[] | { items: CurrencyOption[] }>({
    queryKey: ['currencies'], queryFn: () => api('/currencies'),
  })
  const fetched = asList(currencies.data).filter((item) => typeof item.code === 'string')
  const options = fetched.length ? fetched : fallbackCurrencies
  const popular = options.filter((item) => item.popular)
  const other = options.filter((item) => !item.popular)
  return <Select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} aria-label={ariaLabel} aria-describedby={ariaDescribedby} aria-invalid={ariaInvalid}>
    {allOption && <option value="ALL">{allOption}</option>}
    <optgroup label="Основные валюты">
      {popular.map((item) => <option key={item.code} value={item.code}>{item.code} — {item.name}</option>)}
    </optgroup>
    {other.length > 0 && <optgroup label="Другие валюты">
      {other.map((item) => <option key={item.code} value={item.code}>{item.code} — {item.name}</option>)}
    </optgroup>}
  </Select>
}
