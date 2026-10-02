import { CurrencySelect } from './CurrencySelect'

export function BudgetCurrencyPicker({ value, onChange, combinedAvailable, baseCurrency }: {
  value: string
  onChange: (currency: string) => void
  combinedAvailable?: boolean
  baseCurrency?: string
}) {
  return <label className="currency-picker">Валюта прогноза
    <CurrencySelect value={value} onChange={onChange} aria-label="Валюта прогноза" allOption={combinedAvailable ? `Все валюты → ${baseCurrency ?? 'RUB'} (оценка)` : undefined} />
  </label>
}
