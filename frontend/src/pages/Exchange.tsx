import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Archive, CheckCircle2, Download, FileArchive, FileSpreadsheet, FileUp, ShieldAlert, UploadCloud } from 'lucide-react'
import { api, ApiError, download, jsonBody } from '../lib/api'
import { Badge, Button, Card, Field, PageHeader, Select, State } from '../components/ui'

interface Preview {
  batch_id: string
  status: string
  rows: Array<{ row: number; normalized?: { duplicate_candidate?: boolean } }>
  errors: Array<{ row?: number; message: string }>
  settings?: Record<string, string>
  duplicate_batch?: boolean
}

interface ProjectImportResult { schema_version: number; created: Record<string, number> }

const maxUploadSize = 20 * 1024 * 1024

function projectError(error: Error) {
  if (error instanceof ApiError && error.status === 409) return 'Полный архив можно импортировать только в пустую установку.'
  return error.message
}

export function ExchangePage() {
  const [tab, setTab] = useState<'import' | 'export'>('import')
  const [importMode, setImportMode] = useState<'csv' | 'project'>('csv')
  const [file, setFile] = useState<File | null>(null)
  const [projectFile, setProjectFile] = useState<File | null>(null)
  const [kind, setKind] = useState('transactions')
  const [encoding, setEncoding] = useState('auto')
  const [delimiter, setDelimiter] = useState('auto')
  const [dateFormat, setDateFormat] = useState('iso')
  const [confirmed, setConfirmed] = useState(false)
  const [createReferences, setCreateReferences] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const projectInputRef = useRef<HTMLInputElement>(null)
  const client = useQueryClient()

  const preview = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Выберите CSV-файл')
      const form = new FormData()
      form.append('file', file)
      form.append('import_type', kind)
      if (encoding !== 'auto') form.append('encoding', encoding)
      if (delimiter !== 'auto') form.append('delimiter', delimiter)
      form.append('date_format', dateFormat)
      return api<Preview>('/imports/preview', { method: 'POST', body: form })
    },
    onSuccess: () => { setConfirmed(false); setCreateReferences(false) },
  })
  const confirm = useMutation({
    mutationFn: () => api(`/imports/${preview.data?.batch_id}/confirm`, { method: 'POST', body: jsonBody({ excluded_rows: [], create_references: createReferences }) }),
    onSuccess: () => { setConfirmed(true); client.invalidateQueries() },
  })
  const importProject = useMutation({
    mutationFn: async () => {
      if (!projectFile) throw new Error('Выберите ZIP-архив проекта')
      const form = new FormData()
      form.append('file', projectFile)
      return api<ProjectImportResult>('/imports/project', { method: 'POST', body: form })
    },
    onSuccess: async () => { await client.invalidateQueries() },
  })

  const onFile = (selected?: File) => {
    if (!selected) return
    if (selected.size > maxUploadSize) return window.alert('Файл больше допустимых 20 МиБ')
    setFile(selected)
    preview.reset()
    setConfirmed(false)
    setCreateReferences(false)
  }
  const onProjectFile = (selected?: File) => {
    if (!selected) return
    if (selected.size > maxUploadSize) return window.alert('Файл больше допустимых 20 МиБ')
    setProjectFile(selected)
    importProject.reset()
  }
  const createdCount = Object.values(importProject.data?.created ?? {}).reduce((sum, count) => sum + count, 0)

  return <div className="page"><PageHeader eyebrow="Переносимость" title="Импорт и экспорт" description="Загружайте банковские операции и сохраняйте полную переносимую копию проекта." />
    <div className="tabs"><button type="button" className={tab === 'import' ? 'active' : ''} onClick={() => setTab('import')}><FileUp /> Импорт</button><button type="button" className={tab === 'export' ? 'active' : ''} onClick={() => setTab('export')}><Download /> Экспорт</button></div>
    {tab === 'import' ? <>
      <div className="segmented exchange-import-mode" aria-label="Формат импорта">
        <button type="button" className={importMode === 'csv' ? 'active' : ''} onClick={() => setImportMode('csv')}><FileSpreadsheet /> Табличный CSV</button>
        <button type="button" className={importMode === 'project' ? 'active' : ''} onClick={() => setImportMode('project')}><FileArchive /> Полный архив проекта</button>
      </div>
      {importMode === 'csv' ? <div className="import-layout"><Card><div className="step-title"><span>1</span><div><h2>Выберите данные</h2><p>До подтверждения бюджет не изменится.</p></div></div><div className="form-grid"><Field label="Тип импорта"><Select value={kind} onChange={(e) => setKind(e.target.value)}><option value="transactions">Фактические операции</option><option value="plan_items">Разовый план доходов/расходов</option><option value="loan_schedule">График кредита</option></Select></Field><Field label="Кодировка"><Select value={encoding} onChange={(e) => setEncoding(e.target.value)}><option value="auto">Определить автоматически</option><option value="utf-8">UTF-8</option><option value="utf-8-sig">UTF-8 с BOM</option><option value="cp1251">Windows-1251</option></Select></Field><Field label="Разделитель"><Select value={delimiter} onChange={(e) => setDelimiter(e.target.value)}><option value="auto">Определить автоматически</option><option value=";">Точка с запятой</option><option value=",">Запятая</option><option value="tab">Табуляция</option></Select></Field><Field label="Формат даты"><Select value={dateFormat} onChange={(e) => setDateFormat(e.target.value)}><option value="iso">YYYY-MM-DD</option><option value="dmy_dot">DD.MM.YYYY</option><option value="dmy">DD/MM/YYYY</option><option value="mdy">MM/DD/YYYY</option></Select></Field></div><input ref={inputRef} aria-label="Файл CSV" type="file" accept=".csv,text/csv" hidden onChange={(e) => onFile(e.target.files?.[0])} /><button type="button" className="drop-zone" onClick={() => inputRef.current?.click()} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); onFile(e.dataTransfer.files[0]) }}><UploadCloud /><strong>{file ? file.name : 'Перетащите CSV сюда'}</strong><span>{file ? `${(file.size / 1024).toFixed(1)} КБ` : 'или выберите файл · до 20 МиБ'}</span></button><Button className="full-button" disabled={!file || preview.isPending} onClick={() => preview.mutate()}>{preview.isPending ? 'Проверяем…' : 'Проверить и показать предпросмотр'}</Button>{preview.isError && <div className="form-alert">{preview.error.message}</div>}</Card>
        <Card><div className="step-title"><span>2</span><div><h2>Проверьте результат</h2><p>Дубли отмечаются как кандидаты и не удаляются автоматически.</p></div></div>{confirmed ? <State kind="success" title="Импорт завершён">Данные сохранены атомарно.</State> : preview.data ? <><div className="import-stats"><div><strong>{preview.data.rows.length + preview.data.errors.length}</strong><span>строк</span></div><div><strong className="positive">{preview.data.rows.length}</strong><span>готовы</span></div><div><strong className="warn-text">{preview.data.rows.filter((row) => row.normalized?.duplicate_candidate).length}</strong><span>возможных дублей</span></div></div>{preview.data.errors.length ? <div className="preview-errors"><b>Ошибки</b>{preview.data.errors.slice(0, 5).map((error, index) => <span key={index}>Строка {error.row ?? '—'}: {error.message}</span>)}</div> : <div className="notice notice--calm"><CheckCircle2 /><span>Формат файла прошёл проверку</span></div>}{kind !== 'loan_schedule' && <label className="import-confirm-option"><input type="checkbox" checked={createReferences} onChange={(event) => setCreateReferences(event.target.checked)} /><span><strong>Создать отсутствующие справочники</strong><small>Разрешить создание категорий и тегов, названия которых встретились в CSV.</small></span></label>}<Button className="full-button" disabled={confirm.isPending || Boolean(preview.data.errors.length)} onClick={() => confirm.mutate()}>{confirm.isPending ? 'Импортируем…' : 'Подтвердить импорт'}</Button>{confirm.isError && <div className="form-alert">{confirm.error.message}</div>}</> : <State title="Сначала загрузите файл">Здесь появятся нормализованные значения, ошибки и кандидаты в дубли.</State>}</Card></div>
        : <div className="project-import-layout"><Card><div className="step-title"><span>1</span><div><h2>Выберите канонический архив</h2><p>ZIP должен быть создан действием «Полный архив проекта».</p></div></div><div className="notice"><ShieldAlert /><div><strong>Только для пустой установки</strong><span>Архив не объединяется с текущим бюджетом. Если финансовые данные уже есть, сервер отклонит импорт.</span></div></div><input ref={projectInputRef} aria-label="Архив проекта ZIP" type="file" accept=".zip,application/zip" hidden onChange={(event) => onProjectFile(event.target.files?.[0])} /><button type="button" className="drop-zone" onClick={() => projectInputRef.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); onProjectFile(event.dataTransfer.files[0]) }}><Archive /><strong>{projectFile ? projectFile.name : 'Перетащите ZIP-архив сюда'}</strong><span>{projectFile ? `${(projectFile.size / 1024).toFixed(1)} КБ` : 'manifest.json и машинные CSV · до 20 МиБ'}</span></button><Button className="full-button" disabled={!projectFile || importProject.isPending || importProject.isSuccess} onClick={() => importProject.mutate()}>{importProject.isPending ? 'Проверяем и импортируем…' : 'Импортировать полный проект'}</Button>{importProject.isError && <div className="form-alert">{projectError(importProject.error)}</div>}</Card>
          <Card><div className="step-title"><span>2</span><div><h2>Результат переноса</h2><p>Схема, связи и стабильные идентификаторы проверяются до записи.</p></div></div>{importProject.isSuccess ? <State kind="success" title="Проект импортирован">Создано записей: {createdCount}. Данные сохранены одной транзакцией.</State> : <State title="Архив ещё не импортирован">При ошибке проверки установка останется без частично записанных данных.</State>}</Card></div>}
    </> : <div className="export-grid"><Card className="export-card"><span className="export-icon"><FileSpreadsheet /></span><div><h2>Читаемый CSV</h2><p>Операции для Excel: русские заголовки, UTF-8 BOM и защита от формул.</p><Badge tone="good">Для просмотра</Badge></div><Button variant="secondary" onClick={() => download('/exports/transactions.csv', 'operations.csv')}><Download /> Скачать CSV</Button></Card><Card className="export-card"><span className="export-icon export-icon--blue"><Archive /></span><div><h2>Полный архив проекта</h2><p>ZIP с manifest.json, стабильными ID и всеми финансовыми связями.</p><Badge tone="info">Для переноса</Badge></div><Button onClick={() => download('/exports/project', 'budget-project.zip')}><Download /> Скачать ZIP</Button></Card><div className="notice export-note"><ShieldAlert /><div><strong>Храните архив безопасно</strong><span>Он содержит финансовые данные, но не пароли и активные сессии.</span></div></div></div>}
  </div>
}
