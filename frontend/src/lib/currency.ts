import { currencyDigits } from './format'

export interface CurrencyOption {
  code: string
  name: string
  minor_digits: number
  popular: boolean
}

export interface FxQuote {
  from_currency: string
  to_currency: string
  rate: string
  requested_date: string
  effective_date: string
  source: 'CBR' | 'identity'
  indicative: boolean
}

export const fallbackCurrencies: CurrencyOption[] = [
  ['RUB', 'Российский рубль'], ['USD', 'Доллар США'], ['EUR', 'Евро'],
  ['CNY', 'Китайский юань'], ['GBP', 'Фунт стерлингов'],
  ['CHF', 'Швейцарский франк'], ['JPY', 'Японская иена'],
  ['AED', 'Дирхам ОАЭ'], ['KZT', 'Казахстанский тенге'],
  ['BYN', 'Белорусский рубль'],
].map(([code, name]) => ({ code, name, minor_digits: currencyDigits(code), popular: true }))

export function convertMinor(sourceMinor: number, sourceCurrency: string, targetCurrency: string, rate: string): number {
  if (!Number.isSafeInteger(sourceMinor)) throw new Error('Сумма слишком велика')
  const normalized = rate.trim().replace(',', '.')
  const match = normalized.match(/^(\d+)(?:\.(\d{1,12}))?$/)
  if (!match) throw new Error('Укажите положительный курс с точностью до 12 знаков')
  const fractional = match[2] ?? ''
  const rateNumber = BigInt(match[1] + fractional)
  if (rateNumber <= 0n) throw new Error('Курс должен быть положительным')
  const sourceScale = 10n ** BigInt(currencyDigits(sourceCurrency))
  const targetScale = 10n ** BigInt(currencyDigits(targetCurrency))
  const divisor = sourceScale * 10n ** BigInt(fractional.length)
  const absolute = BigInt(Math.abs(sourceMinor)) * rateNumber * targetScale
  const rounded = (absolute + divisor / 2n) / divisor
  const result = Number(rounded) * (sourceMinor < 0 ? -1 : 1)
  if (!Number.isSafeInteger(result)) throw new Error('Сумма после конвертации слишком велика')
  return result
}

export function moneyInput(minor: number, currency = 'RUB'): string {
  const digits = currencyDigits(currency)
  return (minor / 10 ** digits).toFixed(digits).replace('.', ',')
}
