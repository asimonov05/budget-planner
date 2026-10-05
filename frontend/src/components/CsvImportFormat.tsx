import { formatMoney } from '../lib/format'
import './csv-import-format.css'

interface CsvSpec {
  required: string
  optional: string
  header: string
  examples: string[]
  notes: string[]
  filename: string
}

const formats: Record<string, CsvSpec> = {
  transactions: {
    required: 'date, amount, type, account (или account_id)',
    optional: 'currency, category, tags, description, comment, external_id, merchant_currency, merchant_amount, exchange_rate',
    header: 'date;amount;type;account;currency;category;tags;description;comment;external_id;merchant_currency;merchant_amount;exchange_rate',
    examples: [
      '2026-10-07;1245,67;expense;Основной;RUB;Продукты;семья|повседневное;Покупка;;bank-0001;;;',
      '2026-10-08;950,00;expense;Основной;RUB;Путешествия;;Билет;;bank-0002;EUR;10,00;95',
    ],
    notes: [
      'type: income, expense, refund или adjustment. Для adjustment нужен comment; сумма может быть отрицательной.',
      'amount — фактическое изменение счёта в его валюте. Для покупки в другой валюте вместе заполните merchant_currency, merchant_amount и exchange_rate: единиц валюты счёта за 1 единицу валюты покупки.',
      'tags разделяйте знаком |. Счёт должен существовать; отсутствующие категории и теги создаются только после отдельного подтверждения.',
    ],
    filename: 'transactions-template.csv',
  },
  transfers: {
    required: 'date, amount, from_account (или from_account_id), to_account (или to_account_id)',
    optional: 'from_currency, to_currency, exchange_rate, to_amount, comment',
    header: 'date;from_account;to_account;amount;from_currency;to_currency;exchange_rate;to_amount;comment',
    examples: [
      '2026-10-08;Основной;Накопительный;5000,00;RUB;RUB;1;5000,00;Между своими счетами',
      '2026-10-09;Основной;Доллары;8000,00;RUB;USD;0,0125;100,00;Конвертация',
    ],
    notes: [
      'amount списывается со счёта отправителя; to_amount зачисляется на счёт получателя. Оба счёта должны существовать и отличаться.',
      'Для разных валют exchange_rate обязателен: единиц валюты получателя за 1 единицу валюты отправителя. Если указан to_amount, он должен совпасть с расчётом по курсу; иначе сумма зачисления вычисляется автоматически.',
      'Для одной валюты курс можно оставить пустым или указать 1. Перевод не становится доходом или расходом.',
    ],
    filename: 'transfers-template.csv',
  },
}

export interface CsvPreviewRow {
  row: number
  normalized?: {
    duplicate_candidate?: boolean
    date?: string
    type?: string
    account?: string
    currency?: string
    amount_minor?: number
    merchant_currency?: string | null
    merchant_amount_minor?: number | null
    merchant_exchange_rate?: string | null
    from_account?: string
    to_account?: string
    from_currency?: string
    to_currency?: string
    to_amount_minor?: number
    exchange_rate?: string
  }
}

export function CsvImportFormat({ kind }: { kind: string }) {
  const spec = formats[kind]
  if (!spec) return null
  const content = `\uFEFF${spec.header}\n${spec.examples.join('\n')}\n`
  return <section className="csv-import-format" aria-label={`Формат CSV: ${kind}`}>
    <h3>Формат файла</h3>
    <p><b>Обязательные колонки:</b> {spec.required}</p>
    <p><b>Необязательные:</b> {spec.optional}</p>
    <p>Поддерживаются UTF-8 (в том числе с BOM) и Windows-1251; разделитель — <code>;</code>, запятая или табуляция. Первая строка — заголовки на английском. Пример с <code>;</code> и датой <code>YYYY-MM-DD</code>:</p>
    <pre>{spec.header}{'\n'}{spec.examples.join('\n')}</pre>
    <ul>{spec.notes.map((note) => <li key={note}>{note}</li>)}</ul>
    <p>Суммы записывайте с точностью валюты счёта; лишние десятичные знаки отклоняются. Для разделителя или переноса строки внутри текста используйте CSV-кавычки.</p>
    <a className="button button--secondary" download={spec.filename} href={`data:text/csv;charset=utf-8,${encodeURIComponent(content)}`}>Скачать пример CSV</a>
  </section>
}

export function CsvPreviewRows({ kind, rows }: { kind: string; rows: CsvPreviewRow[] }) {
  if ((kind !== 'transactions' && kind !== 'transfers') || !rows.length) return null
  return <section className="csv-preview-rows" aria-label="Проверенные строки CSV">
    <h3>Что будет импортировано</h3>
    <div className="csv-preview-rows__list">{rows.slice(0, 20).map(({ row, normalized }) => {
      if (!normalized) return null
      const label = kind === 'transactions'
        ? `${normalized.type ?? ''} · ${normalized.account ?? ''}`
        : `${normalized.from_account ?? ''} → ${normalized.to_account ?? ''}`
      const amount = kind === 'transactions'
        ? formatMoney(normalized.amount_minor, normalized.currency ?? 'RUB')
        : `${formatMoney(normalized.amount_minor, normalized.from_currency ?? 'RUB')} → ${formatMoney(normalized.to_amount_minor, normalized.to_currency ?? 'RUB')}`
      const rate = kind === 'transactions' && normalized.merchant_currency
        ? `Покупка ${formatMoney(normalized.merchant_amount_minor ?? undefined, normalized.merchant_currency)} · курс ${normalized.merchant_exchange_rate}`
        : kind === 'transfers' && normalized.from_currency !== normalized.to_currency
          ? `Курс: 1 ${normalized.from_currency} = ${normalized.exchange_rate} ${normalized.to_currency}`
          : null
      return <div key={row}><span>Строка {row} · {normalized.date} · {label}</span><strong>{amount}</strong>{rate && <small>{rate}</small>}{normalized.duplicate_candidate && <small>Возможный дубль</small>}</div>
    })}</div>
    {rows.length > 20 && <small>Показаны первые 20 из {rows.length} готовых строк.</small>}
  </section>
}
