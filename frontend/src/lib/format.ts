const integerPattern = /^-?\d+$/

export function formatMoney(minor?: number, currency = 'RUB', compact = false) {
  const value = (minor ?? 0) / 100
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency', currency, maximumFractionDigits: value % 1 ? 2 : 0,
    ...(compact ? { notation: 'compact' as const } : {}),
  }).format(value)
}

export function parseMoney(value: string): number {
  const normalized = value.trim().replace(/[\s\u00A0]/g, '').replace(',', '.')
  if (!/^-?\d+(?:\.\d{0,2})?$/.test(normalized)) throw new Error('Введите сумму, например 12 345,67')
  const [whole, fraction = ''] = normalized.split('.')
  const sign = whole.startsWith('-') ? -1 : 1
  const absWhole = whole.replace('-', '')
  const minorText = `${absWhole}${fraction.padEnd(2, '0')}`.replace(/^0+(?=\d)/, '')
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
