const integerPattern = /^-?\d+$/

export function currencyDigits(currency = 'RUB'): number {
  try {
    return new Intl.NumberFormat('en', { style: 'currency', currency }).resolvedOptions().maximumFractionDigits ?? 2
  } catch {
    return 2
  }
}

export function formatMoney(minor?: number, currency = 'RUB', compact = false) {
  const digits = currencyDigits(currency)
  const value = (minor ?? 0) / 10 ** digits
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency', currency, minimumFractionDigits: 0,
    maximumFractionDigits: value % 1 ? digits : 0,
    ...(compact ? { notation: 'compact' as const } : {}),
  }).format(value)
}

export function parseMoney(value: string, currency = 'RUB'): number {
  const digits = currencyDigits(currency)
  const normalized = value.trim().replace(/[\s\u00A0]/g, '').replace(',', '.')
  const pattern = digits ? new RegExp(`^-?\\d+(?:\\.\\d{0,${digits}})?$`) : /^-?\d+$/
  if (!pattern.test(normalized)) throw new Error(`Укажите сумму с точностью до ${digits} знаков`)
  const [whole, fraction = ''] = normalized.split('.')
  const sign = whole.startsWith('-') ? -1 : 1
  const absWhole = whole.replace('-', '')
  const minorText = `${absWhole}${fraction.padEnd(digits, '0')}`.replace(/^0+(?=\d)/, '')
  if (!integerPattern.test(minorText || '0')) throw new Error('Некорректная сумма')
  const result = sign * Number(minorText || '0')
  if (!Number.isSafeInteger(result)) throw new Error('Сумма слишком велика')
  return result
}

export function monthLabel(value: string, short = false) {
  const [year, month] = value.split('-').map(Number)
  return new Intl.DateTimeFormat('ru-RU', { month: short ? 'short' : 'long', year: short ? undefined : 'numeric' }).format(new Date(year, month - 1, 1))
}

export function dateLabel(value?: string) {
  if (!value) return 'Без точной даты'
  const [y, m, d] = value.split('-').map(Number)
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(y, m - 1, d))
}

export function todayISO(value = new Date()) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

export function currentMonth(value = new Date()) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}`
}
