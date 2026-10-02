import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, queryString } from '../lib/api'
import { dateLabel, todayISO } from '../lib/format'
import type { FxQuote } from '../lib/currency'
import { CurrencySelect } from './CurrencySelect'
import { Card, Field, Input, State } from './ui'

export function CurrencySettings() {
  const [fromCurrency, setFromCurrency] = useState('USD')
  const [toCurrency, setToCurrency] = useState('RUB')
  const [onDate, setOnDate] = useState(todayISO())
  const quote = useQuery<FxQuote>({
    queryKey: ['currency-quote', fromCurrency, toCurrency, onDate],
    queryFn: () => api(`/currencies/quote?${queryString({ from_currency: fromCurrency, to_currency: toCurrency, on_date: onDate })}`),
    enabled: Boolean(onDate), retry: false,
  })
  return <Card className="settings-card">
    <div className="section-head"><div><span className="eyebrow">Справочник</span><h2>Валюты и курс</h2></div></div>
    <p>Курс Банка России служит подсказкой. Для перевода или оплаты укажите фактический курс вашего банка.</p>
    <div className="form-grid">
      <Field label="Из валюты"><CurrencySelect value={fromCurrency} onChange={setFromCurrency}/></Field>
      <Field label="В валюту"><CurrencySelect value={toCurrency} onChange={setToCurrency}/></Field>
      <Field label="Дата операции"><Input type="date" value={onDate} onChange={(event) => setOnDate(event.target.value)}/></Field>
    </div>
    {quote.isLoading && <State kind="loading" title="Ищем официальный курс"/>}
    {quote.isError && <div className="form-hint">Курс сейчас недоступен. В операции можно указать его вручную.</div>}
    {quote.data && <div className="notice notice--calm">
      <div><strong>1 {fromCurrency} ≈ {quote.data.rate.replace('.', ',')} {toCurrency}</strong>
        <span>{quote.data.source === 'CBR' ? `Банк России · курс на ${dateLabel(quote.data.effective_date)}` : 'Одинаковая валюта'} · фактический курс банка может отличаться.</span>
      </div>
    </div>}
  </Card>
}
