import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bug, ChevronLeft, ChevronRight, Database, RefreshCw, ShieldCheck, Table2 } from 'lucide-react'
import { Navigate } from 'react-router-dom'
import { api, queryString } from '../lib/api'
import type { User } from '../lib/types'
import { Badge, Button, Card, PageHeader, State } from '../components/ui'

interface FileInfo { exists: boolean; size_bytes: number; modified_at?: string }
interface BackupInfo { name: string; size_bytes: number; modified_at: string }
interface DebugOverview {
  application: { version: string; python_version: string; sqlite_version: string; debug_admin_enabled: boolean }
  database: {
    file_name: string
    files: { main: FileInfo; wal: FileInfo; shm: FileInfo }
    journal_mode: string
    foreign_keys: boolean
    synchronous: number
    schema_revision: string | null
    safe_sqlite_required: boolean
  }
  backups: { count: number; total_size_bytes: number; latest: BackupInfo | null }
}
interface DebugTable { name: string; label: string; row_count: number }
interface DebugColumn { name: string; type: string; primary_key: boolean }
interface DebugRows { name: string; label: string; offset: number; limit: number; total: number; columns: DebugColumn[]; rows: Array<Record<string, unknown>> }
interface DatabaseCheck {
  integrity_check: string[]
  integrity_truncated: boolean
  foreign_key_violations: Array<{ table: string; rowid: number | null; parent: string; fkid: number }>
  foreign_keys_truncated: boolean
  ok: boolean
}

const PAGE_SIZE = 50

function formatBytes(value: number) {
  if (value < 1024) return `${value} Б`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} КБ`
  return `${(value / 1024 / 1024).toFixed(1)} МБ`
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) return 'NULL'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function DebugValue({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <div className="debug-value"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>
}

export function DebugAdminPage() {
  const queryClient = useQueryClient()
  const me = useQuery<User>({ queryKey: ['me'], queryFn: () => api<User>('/auth/me') })
  const enabled = me.data?.debug_admin_enabled === true
  const overview = useQuery<DebugOverview>({ queryKey: ['admin-debug-overview'], queryFn: () => api<DebugOverview>('/admin/debug/overview'), enabled })
  const tables = useQuery<DebugTable[]>({ queryKey: ['admin-debug-tables'], queryFn: () => api<DebugTable[]>('/admin/debug/tables'), enabled })
  const [selectedTable, setSelectedTable] = useState('')
  const [offset, setOffset] = useState(0)

  useEffect(() => {
    if (tables.data?.length && !tables.data.some((table) => table.name === selectedTable)) {
      setSelectedTable(tables.data[0].name)
      setOffset(0)
    }
  }, [tables.data, selectedTable])

  const tableRows = useQuery<DebugRows>({
    queryKey: ['admin-debug-rows', selectedTable, offset],
    queryFn: () => api<DebugRows>(`/admin/debug/tables/${encodeURIComponent(selectedTable)}/rows?${queryString({ offset, limit: PAGE_SIZE })}`),
    enabled: enabled && Boolean(selectedTable),
  })
  const databaseCheck = useMutation<DatabaseCheck>({
    mutationFn: () => api<DatabaseCheck>('/admin/debug/database-check', { method: 'POST' }),
  })

  if (me.isLoading) return <div className="page"><State kind="loading" title="Проверяем доступ"/></div>
  if (me.isError) return <div className="page"><State kind="error" title="Не удалось проверить доступ">Обновите страницу и войдите в приложение.</State></div>
  if (!enabled) return <Navigate to="/" replace />

  const db = overview.data?.database
  const selected = tables.data?.find((table) => table.name === selectedTable)
  const rowData = tableRows.data
  const pageNumber = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil((rowData?.total ?? 0) / PAGE_SIZE))

  return <div className="page page--wide">
    <PageHeader
      eyebrow="Отладка · владелец"
      title="Админка"
      description="Состояние приложения, проверка SQLite и просмотр записей базы в режиме только для чтения."
      actions={<Badge tone="warn"><Bug/> DEBUG включён</Badge>}
    />

    <div className="debug-toolbar">
      <span>Диагностические данные видны только после входа владельца.</span>
      <Button variant="secondary" onClick={() => {
        void queryClient.invalidateQueries({ queryKey: ['admin-debug-overview'] })
        void queryClient.invalidateQueries({ queryKey: ['admin-debug-tables'] })
        void queryClient.invalidateQueries({ queryKey: ['admin-debug-rows'] })
      }}><RefreshCw/> Обновить</Button>
    </div>

    {overview.isLoading ? <State kind="loading" title="Собираем сведения о системе"/> : overview.isError ? <State kind="error" title="Не удалось получить состояние системы">{overview.error.message}</State> : overview.data && <>
      <section className="debug-overview-grid" aria-label="Состояние системы">
        <Card className="debug-overview-card"><div className="debug-card-heading"><Database/><h2>Приложение</h2></div>
          <DebugValue label="Версия" value={overview.data.application.version}/>
          <DebugValue label="Python" value={overview.data.application.python_version}/>
          <DebugValue label="SQLite" value={overview.data.application.sqlite_version}/>
        </Card>
        <Card className="debug-overview-card"><div className="debug-card-heading"><Database/><h2>База данных</h2></div>
          <DebugValue label="Файл" value={overview.data.database.file_name}/>
          <DebugValue label="Размер файла" value={formatBytes(db?.files.main.size_bytes ?? 0)} detail={`WAL: ${formatBytes(db?.files.wal.size_bytes ?? 0)} · SHM: ${formatBytes(db?.files.shm.size_bytes ?? 0)}`}/>
          <DebugValue label="Схема" value={db?.schema_revision ?? 'не определена'} detail={`journal_mode: ${db?.journal_mode} · foreign_keys: ${db?.foreign_keys ? 'ON' : 'OFF'}`}/>
        </Card>
        <Card className="debug-overview-card"><div className="debug-card-heading"><ShieldCheck/><h2>Резервные копии</h2></div>
          <DebugValue label="Количество" value={String(overview.data.backups.count)} detail={`Всего: ${formatBytes(overview.data.backups.total_size_bytes)}`}/>
          <DebugValue label="Последняя копия" value={overview.data.backups.latest?.name ?? 'нет копий'} detail={overview.data.backups.latest ? `${formatBytes(overview.data.backups.latest.size_bytes)} · ${new Date(overview.data.backups.latest.modified_at).toLocaleString('ru-RU')}` : undefined}/>
        </Card>
      </section>

      <Card className="debug-check-card">
        <div className="section-head"><div><span className="eyebrow">Проверка по запросу</span><h2>Целостность базы</h2></div>
          <Button variant="secondary" disabled={databaseCheck.isPending} onClick={() => databaseCheck.mutate()}><ShieldCheck/>{databaseCheck.isPending ? 'Проверяем…' : 'Проверить базу'}</Button>
        </div>
        <p className="debug-help">Проверка SQLite может занять время на большой базе. Она не меняет данные.</p>
        {databaseCheck.isError && <div className="form-alert" role="alert">{databaseCheck.error.message}</div>}
        {databaseCheck.data && <div className="debug-check-result">
          <Badge tone={databaseCheck.data.ok ? 'good' : 'danger'}>{databaseCheck.data.ok ? 'Проверка пройдена' : 'Найдены проблемы'}</Badge>
          <span>integrity_check: {databaseCheck.data.integrity_check.join(', ') || 'нет результата'}{databaseCheck.data.integrity_truncated ? ' (список сокращён)' : ''}</span>
          <span>Нарушения внешних ключей: {databaseCheck.data.foreign_key_violations.length}{databaseCheck.data.foreign_keys_truncated ? ' (показаны первые 50)' : ''}</span>
          {databaseCheck.data.foreign_key_violations.length > 0 && <pre>{JSON.stringify(databaseCheck.data.foreign_key_violations, null, 2)}</pre>}
        </div>}
      </Card>
    </>}

    <Card className="debug-browser-card">
      <div className="section-head"><div><span className="eyebrow">Только чтение</span><h2>Данные базы</h2></div><Table2/></div>
      {tables.isLoading ? <State kind="loading" title="Загружаем список таблиц"/> : tables.isError ? <State kind="error" title="Не удалось загрузить таблицы">{tables.error.message}</State> : <>
        <div className="debug-browser-toolbar">
          <label className="field"><span>Таблица</span><select className="input" value={selectedTable} onChange={(event) => { setSelectedTable(event.target.value); setOffset(0) }}>
            {tables.data?.map((table) => <option key={table.name} value={table.name}>{table.label} · {table.name} ({table.row_count})</option>)}
          </select></label>
          {selected && <span className="debug-row-count">Записей: {selected.row_count.toLocaleString('ru-RU')}</span>}
        </div>
        {tableRows.isLoading ? <State kind="loading" title="Загружаем строки"/> : tableRows.isError ? <State kind="error" title="Не удалось прочитать таблицу">{tableRows.error.message}</State> : rowData && <>
          <div className="debug-data-wrap"><table className="debug-data-table"><thead><tr>{rowData.columns.map((column) => <th key={column.name} title={`${column.type}${column.primary_key ? ' · primary key' : ''}`}>{column.name}{column.primary_key && <small> PK</small>}</th>)}</tr></thead>
            <tbody>{rowData.rows.map((row, index) => <tr key={`${offset}-${index}`}>{rowData.columns.map((column) => {
              const fullValue = formatCell(row[column.name])
              return <td key={column.name} title={fullValue}><span>{fullValue.length > 180 ? `${fullValue.slice(0, 180)}…` : fullValue}</span></td>
            })}</tr>)}</tbody>
          </table></div>
          {rowData.rows.length === 0 ? <State title="Таблица пуста"/> : <div className="debug-pagination">
            <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}><ChevronLeft/> Назад</Button>
            <span>Страница {pageNumber} из {pageCount} · строк {offset + 1}–{Math.min(offset + PAGE_SIZE, rowData.total)} из {rowData.total}</span>
            <Button variant="secondary" disabled={offset + PAGE_SIZE >= rowData.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Дальше <ChevronRight/></Button>
          </div>}
        </>}
      </>}
    </Card>
  </div>
}
