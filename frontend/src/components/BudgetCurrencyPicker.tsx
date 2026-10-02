import { CurrencySelect } from './CurrencySelect'

export function BudgetCurrencyPicker({ value, onChange }: {
  value: string
  onChange: (currency: string) => void
}) {
  return <label className="currency-picker">Валюта прогноза
    <CurrencySelect value={value} onChange={onChange} aria-label="Валюта прогноза" />
  </label>
}
