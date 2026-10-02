import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, jsonBody, queryString } from '../lib/api'
import { dateLabel, todayISO } from '../lib/format'
import type { FxQuote } from '../lib/currency'
import { CurrencySelect } from './CurrencySelect'
import { Button, Card, Field, Input, Select, State } from './ui'

interface DisplaySettings { currency: string; currency_display_mode: 'separate' | 'converted'; version: number }
interface DisplayRate { from_currency: string; to_currency: string; rate: string | null; updated_on: string | null; required: boolean }
interface DisplayRates { base_currency: string; version: number | null; items: DisplayRate[] }

export function CurrencySettings() {
  const client = useQueryClient()
  const settings = useQuery<DisplaySettings>({ queryKey: ['settings'], queryFn: () => api('/settings') })
  const displayRates = useQuery<DisplayRates>({ queryKey: ['display-rates'], queryFn: () => api('/currencies/display-rates'), enabled: Boolean(settings.data) })
  const [draftMode, setDraftMode] = useState<'separate' | 'converted' | null>(null)
  const [draftRates, setDraftRates] = useState<Record<string, string>>({})
  const [fromCurrency, setFromCurrency] = useState('USD')
  const [toCurrency, setToCurrency] = useState('RUB')
  const [onDate, setOnDate] = useState(todayISO())
  const baseCurrency = settings.data?.currency ?? 'RUB'
  const mode = draftMode ?? settings.data?.currency_display_mode ?? 'separate'
  const savedRate = displayRates.data?.items.find((item) => item.from_currency === fromCurrency)
  const enteredRate = draftRates[fromCurrency] ?? savedRate?.rate?.replace('.', ',') ?? ''
  useEffect(() => { setToCurrency(baseCurrency) }, [baseCurrency])
  const invalidate = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['settings'] }),
      client.invalidateQueries({ queryKey: ['display-rates'] }),
      client.invalidateQueries({ queryKey: ['accounts'] }),
      client.invalidateQueries({ queryKey: ['forecast'] }),
      client.invalidateQueries({ queryKey: ['analytics'] }),
    ])
  }
  const save = useMutation({
    mutationFn: () => api('/settings', { method: 'PATCH', body: jsonBody({ currency_display_mode: mode, version: settings.data?.version }) }),
    onSuccess: async () => { setDraftMode(null); await invalidate() },
  })
  const saveRate = useMutation({
    mutationFn: () => api(`/currencies/display-rates/${fromCurrency}`, {
      method: 'PUT', body: jsonBody({ rate: enteredRate.trim().replace(',', '.'), version: displayRates.data?.version }),
    }),
    onSuccess: async () => {
      setDraftRates((current) => { const updated = { ...current }; delete updated[fromCurrency]; return updated })
      await invalidate()
    },
  })
  const deleteRate = useMutation({
    mutationFn: () => api(`/currencies/display-rates/${fromCurrency}?${queryString({ version: displayRates.data?.version ?? undefined })}`, { method: 'DELETE' }),
    onSuccess: async () => { setDraftRates((current) => ({ ...current, [fromCurrency]: '' })); await invalidate() },
  })
  const quote = useQuery<FxQuote>({
    queryKey: ['currency-quote', fromCurrency, toCurrency, onDate],
    queryFn: () => api(`/currencies/quote?${queryString({ from_currency: fromCurrency, to_currency: toCurrency, on_date: onDate })}`),
    enabled: Boolean(onDate), retry: false,
  })
  return <Card className="settings-card">
    <div className="section-head"><div><span className="eyebrow">Справочник</span><h2>Валюты и курс</h2></div></div>
    <Field label="Баланс и прогноз" hint="Влияет только на показ итогов; суммы операций и остатки счетов сохраняются в их валютах">
      <Select value={mode} onChange={(event) => setDraftMode(event.target.value as 'separate' | 'converted')}>
        <option value="separate">Отдельно по каждой валюте</option>
        <option value="converted">Общий ориентировочный итог в {settings.data?.currency ?? 'RUB'}</option>
      </Select>
    </Field>
    <div className="form-actions"><Button disabled={!draftMode || !settings.data || save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Сохраняем…' : 'Сохранить способ показа'}</Button></div>
    {save.isError && <div className="form-alert" role="alert">{save.error.message}</div>}
    <h3>Курсы для общего итога</h3>
    <p>Укажите вручную, сколько {baseCurrency} приходится на единицу другой валюты. Заданный курс действует для всех месяцев прогноза, пока вы его не измените. Курс ЦБ ниже служит только подсказкой.</p>
    {displayRates.isLoading && <State kind="loading" title="Загружаем заданные курсы"/>}
    {displayRates.isError && <div className="form-alert" role="alert">{displayRates.error.message}</div>}
    {displayRates.data && <div className="form-stack">
      {displayRates.data.items.map((item) => <div key={item.from_currency} className="fx-preview"><strong>{item.from_currency} → {item.to_currency}: {item.rate ? item.rate.replace('.', ',') : 'курс не задан'}</strong><small>{item.rate ? `Установлен ${dateLabel(item.updated_on ?? undefined)}` : 'Нужен для общего итога'}{item.required ? ' · используется в бюджете' : ''}</small></div>)}
      <div className="form-grid">
        <Field label="Валюта для итога"><CurrencySelect value={fromCurrency} onChange={setFromCurrency}/></Field>
        <Field label={`Курс: 1 ${fromCurrency} в ${baseCurrency}`}><Input inputMode="decimal" value={enteredRate} onChange={(event) => setDraftRates((current) => ({ ...current, [fromCurrency]: event.target.value }))} placeholder="Например, 80,50"/></Field>
      </div>
      <div className="form-actions">
        <Button disabled={!enteredRate.trim() || fromCurrency === baseCurrency || !displayRates.data.version || saveRate.isPending} onClick={() => saveRate.mutate()}>{saveRate.isPending ? 'Сохраняем…' : 'Сохранить курс'}</Button>
        {savedRate?.rate && <Button variant="ghost" disabled={deleteRate.isPending} onClick={() => deleteRate.mutate()}>Удалить курс</Button>}
      </div>
      {saveRate.isError && <div className="form-alert" role="alert">{saveRate.error.message}</div>}
      {deleteRate.isError && <div className="form-alert" role="alert">{deleteRate.error.message}</div>}
    </div>}
    <h3>Подсказка Банка России</h3>
    <div className="form-grid">
      <Field label="Из валюты"><CurrencySelect value={fromCurrency} onChange={setFromCurrency}/></Field>
      <Field label="В валюту"><CurrencySelect value={toCurrency} onChange={setToCurrency}/></Field>
      <Field label="Дата курса"><Input type="date" value={onDate} onChange={(event) => setOnDate(event.target.value)}/></Field>
    </div>
    {quote.isLoading && <State kind="loading" title="Ищем официальный курс"/>}
    {quote.isError && <div className="form-hint">Курс ЦБ сейчас недоступен. Введите свой курс вручную.</div>}
    {quote.data && <div className="notice notice--calm">
      <div><strong>1 {fromCurrency} ≈ {quote.data.rate.replace('.', ',')} {toCurrency}</strong>
        <span>{quote.data.source === 'CBR' ? `Банк России · курс на ${dateLabel(quote.data.effective_date)}` : 'Одинаковая валюта'} · ориентир, а не фактический курс банка.</span>
        {toCurrency === baseCurrency && fromCurrency !== baseCurrency && <Button variant="secondary" onClick={() => setDraftRates((current) => ({ ...current, [fromCurrency]: quote.data!.rate.replace('.', ',') }))}>Подставить в поле выше</Button>}
      </div>
    </div>}
  </Card>
}
