import { useMutation } from '@tanstack/react-query'
import { api, asList } from '../lib/api'
import type { Account, ListResponse } from '../lib/types'
import { Button, Card } from './ui'

const skillPath = '/skills/bank-pdf-to-budget-csv/SKILL.md'

export function makeAccountReference(accounts: Account[], exportedAt: string) {
  return {
    format: 'budget-planner-account-reference-v1',
    exported_at: exportedAt,
    accounts: accounts.map((account) => ({
      account_id: Number(account.id),
      name: account.name,
      currency: account.currency ?? 'RUB',
      type: account.type ?? 'bank',
      archived: Boolean(account.archived),
      initial_balance_date: account.initial_balance_date ?? null,
    })),
  }
}

function saveAccountReference(accounts: Account[]) {
  const payload = makeAccountReference(accounts, new Date().toISOString())
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'accounts-for-import.json'
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function BankPdfGuide() {
  const exportAccounts = useMutation({
    mutationFn: async () => {
      const response = await api<Account[] | ListResponse<Account>>('/accounts?include_archived=true')
      const accounts = asList(response)
      if (!accounts.length) throw new Error('Сначала добавьте счета в настройках бюджета.')
      return accounts
    },
    onSuccess: saveAccountReference,
  })
  return <Card className="bank-pdf-guide">
    <span className="eyebrow">Выписка банка в PDF</span>
    <h2>Как подготовить PDF к импорту</h2>
    <p>Приложение принимает CSV. Скилл описывает, как локально извлечь из банковского PDF операции, отделить переводы между своими счетами, сверить суммы и получить два файла в нужном формате.</p>
    <ol>
      <li>Скачайте список счетов с их ID и валютами из приложения.</li>
      <li>Передайте ИИ этот JSON, PDF-выписку и скилл. Сверьте предложенное сопоставление счетов.</li>
      <li>Получите <code>transactions.csv</code> и <code>transfers.csv</code>, затем загрузите их по отдельности и проверьте предпросмотр.</li>
    </ol>
    <div className="page-actions">
      <Button variant="secondary" disabled={exportAccounts.isPending} onClick={() => exportAccounts.mutate()}>{exportAccounts.isPending ? 'Готовим список…' : 'Скачать счета для ИИ'}</Button>
      <a className="button button--primary" href={skillPath} target="_blank" rel="noopener noreferrer">Открыть скилл</a>
      <a className="button button--secondary" href={skillPath} download="bank-pdf-to-budget-csv-SKILL.md">Скачать SKILL.md</a>
    </div>
    {exportAccounts.isError && <small role="alert">{exportAccounts.error.message}</small>}
    <small>Выгрузка счетов содержит ID, названия, валюты и даты открытия — без остатков, паролей и токенов. Решение передать её внешнему ИИ остаётся за вами.</small>
  </Card>
}
