import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, CheckCircle2, CirclePlus, FolderCog, Monitor, Moon, Palette, Pencil, RotateCcw, Sun, Tags, Trash2, WalletCards } from 'lucide-react'
import { ApiError, api, asList, jsonBody, queryString } from '../lib/api'
import { formatMoney, parseMoney, todayISO } from '../lib/format'
import { useTheme, type ColorScheme, type FontChoice, type ThemePreference } from '../lib/theme'
import type { Account, Category, ID, ListResponse, Tag } from '../lib/types'
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, State } from '../components/ui'
import { SalarySettings } from '../components/SalarySettings'
import { PrivateUsers } from '../components/PrivateUsers'
import type { User } from '../lib/types'

type Tab = 'general'|'salary'|'appearance'|'accounts'|'categories'|'tags'|'users'
interface Settings { currency: string; timezone: string; accounting_start_date?: string; locale?: string; salary_enabled: boolean; version: number }
type DirectoryKind = 'accounts'|'categories'|'tags'
type DirectoryItem = Account|Category|Tag

function itemVersion(item: DirectoryItem) { return item.version ?? 1 }
function actionError(error: Error | null) {
  if (!error) return null
  return error instanceof ApiError && error.status === 409
    ? `${error.message}. Обновите список и повторите действие.`
    : error.message
}

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>(() => {
    const requested = new URLSearchParams(window.location.search).get('tab')
    return requested === 'salary' || requested === 'accounts' ? requested : 'general'
  })
  const me = useQuery<User>({ queryKey: ['me'], queryFn: () => api('/auth/me') })
  return <div className="page"><PageHeader eyebrow="Система" title="Настройки" description="Параметры бюджета, зарплата, оформление, справочники."/><div className="settings-layout"><aside className="settings-nav"><button className={tab==='general'?'active':''} onClick={() => setTab('general')}><FolderCog/> Основные</button><button className={tab==='salary'?'active':''} onClick={() => setTab('salary')}><WalletCards/> Зарплата</button><button className={tab==='appearance'?'active':''} onClick={() => setTab('appearance')}><Palette/> Оформление</button><button className={tab==='accounts'?'active':''} onClick={() => setTab('accounts')}><WalletCards/> Счета</button><button className={tab==='categories'?'active':''} onClick={() => setTab('categories')}><Archive/> Категории</button><button className={tab==='tags'?'active':''} onClick={() => setTab('tags')}><Tags/> Теги</button>{me.data?.is_admin && <button className={tab==='users'?'active':''} onClick={() => setTab('users')}><WalletCards/> Пользователи</button>}</aside><section>{tab === 'general' && <GeneralSettings/>}{tab === 'salary' && <SalarySettings/>}{tab === 'appearance' && <AppearanceSettings/>}{tab === 'accounts' && <Directory kind="accounts"/>}{tab === 'categories' && <Directory kind="categories"/>}{tab === 'tags' && <Directory kind="tags"/>}{tab === 'users' && me.data?.is_admin && <PrivateUsers/>}</section></div></div>
}

function GeneralSettings() {
  const client = useQueryClient(); const settings = useQuery<Settings>({ queryKey: ['settings'], queryFn: () => api('/settings') })
  const [draft, setDraft] = useState<Settings|null>(null); const value = draft ?? settings.data
  const save = useMutation({ mutationFn: () => api('/settings', { method: 'PATCH', body: jsonBody({ currency: value?.currency, timezone: value?.timezone, accounting_start_date: value?.accounting_start_date, version: value?.version }) }), onSuccess: () => { client.invalidateQueries({ queryKey: ['settings'] }); setDraft(null) } })
  if (settings.isLoading) return <State kind="loading" title="Загружаем настройки"/>; if (!value) return <State kind="error" title="Настройки недоступны"/>
  return <><Card className="settings-card"><div className="section-head"><div><span className="eyebrow">Бюджет</span><h2>Основные параметры</h2></div></div><div className="form-grid"><Field label="Валюта" hint="Нельзя просто переименовать суммы после начала учёта"><Select value={value.currency} onChange={(e) => setDraft({...value,currency:e.target.value})}><option value="RUB">RUB — российский рубль</option></Select></Field><Field label="Часовой пояс"><Input value={value.timezone} onChange={(e) => setDraft({...value,timezone:e.target.value})}/></Field><Field label="Дата начала учёта"><Input type="date" value={value.accounting_start_date ?? ''} onChange={(e) => setDraft({...value,accounting_start_date:e.target.value})}/></Field></div><div className="form-actions"><Button disabled={!draft || save.isPending} onClick={() => save.mutate()}>{save.isPending?'Сохраняем…':'Сохранить'}</Button></div>{save.isError && <div className="form-alert">{save.error.message}</div>}</Card><ResetBudget/></>
}

function ResetBudget() {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [done, setDone] = useState(false)
  const reset = useMutation({
    mutationFn: () => api('/budget/reset', { method: 'POST', body: jsonBody({ password, confirmation }) }),
    onSuccess: () => {
      client.clear()
      setPassword('')
      setConfirmation('')
      setOpen(false)
      setDone(true)
    },
  })
  return <Card className="settings-card"><div className="section-head"><div><span className="eyebrow">Импорт</span><h2>Сбросить свой бюджет</h2></div></div><p>Удаляет ваши финансовые данные перед повторным импортом ZIP. Учётная запись и текущий вход сохраняются; остальные ваши сессии завершатся.</p><Button variant="secondary" onClick={() => { setDone(false); reset.reset(); setOpen(true) }}>Сбросить бюджет</Button>{done && <div className="notice notice--calm">Бюджет очищен. Теперь можно импортировать ZIP-архив проекта.</div>}{open && <Modal title="Сбросить свой бюджет" onClose={() => setOpen(false)}><div className="form-stack"><Field label="Текущий пароль"><Input type="password" value={password} onChange={(event) => setPassword(event.target.value)}/></Field><Field label="Напишите RESET"><Input value={confirmation} onChange={(event) => setConfirmation(event.target.value)}/></Field>{reset.isError && <div className="form-alert" role="alert">{reset.error.message}</div>}<div className="form-actions"><Button variant="ghost" onClick={() => setOpen(false)}>Отмена</Button><Button disabled={!password || confirmation !== 'RESET' || reset.isPending} onClick={() => reset.mutate()}>{reset.isPending ? 'Сбрасываем…' : 'Подтвердить сброс'}</Button></div></div></Modal>}</Card>
}

const themeChoices: Array<{
  value: ThemePreference
  title: string
  description: string
  icon: typeof Sun
}> = [
  { value: 'light', title: 'Светлая', description: 'Светлый фон и спокойные контрастные поверхности.', icon: Sun },
  { value: 'dark', title: 'Тёмная', description: 'Меньше яркости вечером и в слабо освещённой комнате.', icon: Moon },
  { value: 'system', title: 'Системная', description: 'Следует за настройкой macOS, Windows или браузера.', icon: Monitor },
]

const colorSchemeChoices: Array<{
  value: ColorScheme
  title: string
  description: string
}> = [
  { value: 'forest', title: 'Лес', description: 'Спокойный зелёный — базовая палитра.' },
  { value: 'ocean', title: 'Океан', description: 'Холодные синие и бирюзовые оттенки.' },
  { value: 'plum', title: 'Слива', description: 'Мягкий фиолетовый акцент.' },
  { value: 'amber', title: 'Янтарь', description: 'Тёплые золотистые оттенки.' },
]

const fontChoices: Array<{
  value: FontChoice
  title: string
  description: string
}> = [
  { value: 'classic', title: 'Классический', description: 'Привычный текст и выразительные заголовки.' },
  { value: 'golos', title: 'Golos Text', description: 'Современный шрифт для текста и заголовков.' },
]

function AppearanceSettings() {
  const { preference, resolvedTheme, colorScheme, fontChoice, setPreference, setColorScheme, setFontChoice } = useTheme()
  const activeColorScheme = colorSchemeChoices.find((choice) => choice.value === colorScheme)!
  return <Card className="settings-card appearance-card">
    <div className="section-head"><div><span className="eyebrow">Интерфейс</span><h2>Тема оформления</h2></div></div>
    <p className="appearance-intro">Выбор применяется сразу и сохраняется только в этом браузере.</p>
    <div className="appearance-options" role="radiogroup" aria-label="Тема интерфейса">
      {themeChoices.map(({ value, title, description, icon: Icon }) => {
        const selected = preference === value
        return <label
          key={value}
          className={`theme-choice ${selected ? 'is-selected' : ''}`}
        >
          <input
            className="theme-choice-input"
            type="radio"
            name="interface-theme"
            value={value}
            checked={selected}
            onChange={() => setPreference(value)}
          />
          <span className={`theme-preview theme-preview--${value}`} aria-hidden="true"><i/><i/><i/></span>
          <span className="theme-choice-copy"><span><Icon/>{title}</span><small>{description}</small></span>
          <span className="theme-choice-check" aria-hidden="true">{selected && <CheckCircle2/>}</span>
        </label>
      })}
    </div>
    <div className="appearance-subsection"><span className="eyebrow">Акцент</span><h3>Цветовая схема</h3><p>Меняет акцентные цвета, фон навигации и оттенок поверхностей.</p></div>
    <div className="color-scheme-options" role="radiogroup" aria-label="Цветовая схема">
      {colorSchemeChoices.map(({ value, title, description }) => {
        const selected = colorScheme === value
        return <label key={value} className={`color-scheme-choice color-scheme-choice--${value} ${selected ? 'is-selected' : ''}`}>
          <input
            className="theme-choice-input"
            type="radio"
            name="interface-color-scheme"
            value={value}
            checked={selected}
            onChange={() => setColorScheme(value)}
          />
          <span className="color-scheme-swatch" aria-hidden="true"><i/><i/><i/></span>
          <span className="color-scheme-copy"><strong>{title}</strong><small>{description}</small></span>
          <span className="color-scheme-check" aria-hidden="true">{selected && <CheckCircle2/>}</span>
        </label>
      })}
    </div>
    <div className="appearance-subsection"><span className="eyebrow">Типографика</span><h3>Шрифт</h3><p>Выберите начертание, удобное для чтения бюджета.</p></div>
    <div className="font-choice-options" role="radiogroup" aria-label="Шрифт интерфейса">
      {fontChoices.map(({ value, title, description }) => {
        const selected = fontChoice === value
        return <label key={value} className={`font-choice font-choice--${value} ${selected ? 'is-selected' : ''}`}>
          <input
            className="theme-choice-input"
            type="radio"
            name="interface-font"
            value={value}
            checked={selected}
            onChange={() => setFontChoice(value)}
          />
          <span className="font-choice-preview" aria-hidden="true"><strong>Бюджет на месяц</strong><small>Доходы, расходы и цели</small></span>
          <span className="font-choice-copy"><strong>{title}</strong><small>{description}</small></span>
          <span className="font-choice-check" aria-hidden="true">{selected && <CheckCircle2/>}</span>
        </label>
      })}
    </div>
    <div className="notice notice--calm appearance-status"><Palette/><div><strong>{activeColorScheme.title}: сейчас используется {resolvedTheme === 'dark' ? 'тёмная' : 'светлая'} палитра</strong><span>{preference === 'system' ? 'Яркость изменится автоматически вместе с системной темой.' : 'Автоматическое переключение яркости выключено.'}</span></div></div>
  </Card>
}

function Directory({ kind }: { kind: DirectoryKind }) {
  const [open,setOpen] = useState(false)
  const [editing,setEditing] = useState<DirectoryItem|null>(null)
  const client = useQueryClient()
  const list = useQuery<DirectoryItem[]|ListResponse<DirectoryItem>>({ queryKey:[kind,'all'],queryFn:()=>api(`/${kind}?include_archived=true`) })
  const state = useMutation<unknown,Error,{item:DirectoryItem;archived:boolean}>({
    mutationFn:({item,archived})=>api(`/${kind}/${item.id}`,{method:'PATCH',body:jsonBody({archived,version:itemVersion(item)})}),
    onSuccess:()=>client.invalidateQueries({queryKey:[kind]}),
  })
  const remove = useMutation<unknown,Error,DirectoryItem>({
    mutationFn:(item)=>api(`/${kind}/${item.id}?${queryString({version:itemVersion(item)})}`,{method:'DELETE'}),
    onSuccess:()=>client.invalidateQueries({queryKey:[kind]}),
  })
  const labels = {accounts:['Счета','счёт'],categories:['Категории','категорию'],tags:['Теги','тег']}[kind]
  const error = actionError(state.error ?? remove.error)
  return <Card className="settings-card"><div className="section-head"><div><span className="eyebrow">Справочник</span><h2>{labels[0]}</h2></div><Button onClick={()=>{state.reset();remove.reset();setEditing(null);setOpen(true)}}><CirclePlus/> Добавить</Button></div>
    {error&&<div className="form-alert" role="alert">{error}</div>}
    {list.isLoading?<State kind="loading" title="Загружаем"/>:list.isError?<State kind="error" title="Не удалось загрузить справочник">{list.error.message}</State>:asList(list.data).length?<div className="directory-list">{asList(list.data).map((item)=><div key={item.id}><span className="color-dot" style={{background:'color' in item ? item.color ?? '#557a5d' : '#557a5d'}}/><div><strong>{item.name}</strong><small>{'current_balance_minor' in item ? `${formatMoney(item.current_balance_minor)} · ${item.archived?'в архиве':'активен'}` : `${item.archived?'В архиве':'Активно'}${'monthly_estimate' in item && item.monthly_estimate ? ' · Оценка по среднему' : ''}`}</small></div>{item.archived&&<Badge>Архив</Badge>}<div className="directory-actions"><button className="icon-button" aria-label={`Изменить ${item.name}`} title="Изменить" onClick={()=>{state.reset();remove.reset();setOpen(false);setEditing(item)}}><Pencil/></button><button className="icon-button" aria-label={`${item.archived?'Восстановить':'Архивировать'} ${item.name}`} title={item.archived?'Восстановить':'Архивировать'} onClick={()=>{
      state.reset();remove.reset()
      if(item.archived||window.confirm(`Архивировать ${labels[1]} «${item.name}»? История сохранится.`))state.mutate({item,archived:!item.archived})
    }}>{item.archived?<RotateCcw/>:<Archive/>}</button><button className="icon-button icon-button--danger" aria-label={`Удалить ${item.name}`} title="Удалить" onClick={()=>{
      state.reset();remove.reset()
      if(window.confirm(`Удалить ${labels[1]} «${item.name}» безвозвратно? Связанный с историей объект удалить нельзя.`))remove.mutate(item)
    }}><Trash2/></button></div></div>)}</div>:<State title={`${labels[0]} пока не добавлены`}/>} 
    {(open||editing)&&<DirectoryForm kind={kind} item={editing??undefined} onClose={()=>{setOpen(false);setEditing(null)}}/>}
  </Card>
}

function DirectoryForm({kind,item,onClose}:{kind:DirectoryKind;item?:DirectoryItem;onClose:()=>void}) {
  const account=item&&'type'in item?item as Account:undefined
  const category=item&&'kind'in item?item as Category:undefined
  const [name,setName]=useState(item?.name??'')
  const [extra,setExtra]=useState(item&&'color'in item?item.color??'#557a5d':'')
  const [accountType,setAccountType]=useState<'cash'|'bank'|'savings'>((account?.type as 'cash'|'bank'|'savings'|undefined)??'bank')
  const [openingDate,setOpeningDate]=useState(account?.initial_balance_date??todayISO())
  const [categoryKind,setCategoryKind]=useState<'income'|'expense'>((category?.kind??category?.type??'expense') as 'income'|'expense')
  const [monthlyEstimate,setMonthlyEstimate]=useState(category?.monthly_estimate??false)
  const client=useQueryClient()
  const save=useMutation({mutationFn:()=>item
    ? api(`/${kind}/${item.id}`,{method:'PATCH',body:jsonBody(kind==='accounts'?{name:name.trim(),type:accountType,version:itemVersion(item)}:{name:name.trim(),color:extra||'#557a5d',...(kind==='categories'?{monthly_estimate:monthlyEstimate}:{}),version:itemVersion(item)})})
    : api(`/${kind}`,{method:'POST',body:jsonBody(kind==='accounts'?{name:name.trim(),type:accountType,initial_balance_minor:parseMoney(extra||'0'),initial_balance_date:openingDate}:{name:name.trim(),color:extra||'#557a5d',...(kind==='categories'?{kind:categoryKind,monthly_estimate:monthlyEstimate}:{})})}),
    onSuccess:()=>{client.invalidateQueries({queryKey:[kind]});client.invalidateQueries({queryKey:['forecast']});client.invalidateQueries({queryKey:['analytics']});onClose()},
  })
  const dirty=name!==(item?.name??'')||(kind==='accounts'?accountType!==(account?.type??'bank'):extra!==(item&&'color'in item?item.color??'#557a5d':''))||(kind==='categories'&&monthlyEstimate!==(category?.monthly_estimate??false))
  const close=()=>{if(!dirty||window.confirm('Закрыть форму и потерять несохранённые изменения?'))onClose()}
  return <Modal title={item?`Изменить «${item.name}»`:'Новая запись'} onClose={close}><div className="form-stack">
    <Field label="Название"><Input autoFocus value={name} onChange={(e)=>setName(e.target.value)}/></Field>
    {kind==='accounts' ? <>
      <Field label="Тип счёта"><Select value={accountType} onChange={(e)=>setAccountType(e.target.value as typeof accountType)}><option value="bank">Банковский счёт / карта</option><option value="cash">Наличные</option><option value="savings">Накопительный счёт</option></Select></Field>
      {!item&&<><Field label="Начальный остаток"><Input value={extra} onChange={(e)=>setExtra(e.target.value)} placeholder="0,00"/></Field><Field label="Остаток на начало даты"><Input type="date" value={openingDate} onChange={(e)=>setOpeningDate(e.target.value)}/></Field></>}
    </> : <>
      {kind==='categories' && <Field label="Тип категории" hint={item?'Тип существующей категории нельзя изменить':undefined}><Select value={categoryKind} disabled={Boolean(item)} onChange={(e)=>{setCategoryKind(e.target.value as typeof categoryKind);if(e.target.value==='income')setMonthlyEstimate(false)}}><option value="expense">Расход</option><option value="income">Доход</option></Select></Field>}
      <Field label="Цвет"><Input type="color" value={extra||'#557a5d'} onChange={(e)=>setExtra(e.target.value)}/></Field>
      {kind==='categories'&&categoryKind==='expense'&&<label className="import-confirm-option"><input type="checkbox" checked={monthlyEstimate} onChange={(e)=>setMonthlyEstimate(e.target.checked)}/><span><strong>Оценивать расход каждый месяц</strong><small>Прогноз добавит недостающую сумму по среднему факту завершённых месяцев. Уже учтённые траты, планы и лимит не удваиваются.</small></span></label>}
    </>}
    {save.isError&&<div className="form-alert" role="alert">{actionError(save.error)}</div>}
    <div className="form-actions"><Button variant="ghost" onClick={close}>Отмена</Button><Button disabled={!name.trim()||(!item&&kind==='accounts'&&!openingDate)||save.isPending} onClick={()=>save.mutate()}>{save.isPending?'Сохраняем…':item?'Сохранить изменения':'Добавить'}</Button></div>
  </div></Modal>
}
