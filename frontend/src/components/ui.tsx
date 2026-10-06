import { cloneElement, forwardRef, isValidElement, useEffect, useId, useRef, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode } from 'react'
import { AlertCircle, CheckCircle2, Inbox, LoaderCircle, X } from 'lucide-react'

export function Button({ className = '', variant = 'primary', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger' }) {
  return <button className={`button button--${variant} ${className}`} {...props} />
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className = '', ...props }, ref) {
  return <input ref={ref} className={`input ${className}`} {...props} />
})

export const Select = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className = '', ...props }, ref) {
  return <select ref={ref} className={`input ${className}`} {...props} />
})

export function Card({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) { return <div className={`card ${className}`} {...props} /> }

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) {
  return <header className="page-header">
    <div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1>{description && <p>{description}</p>}</div>
    {actions && <div className="page-actions">{actions}</div>}
  </header>
}

export function State({ kind = 'empty', title, children, action }: { kind?: 'loading' | 'empty' | 'error' | 'success'; title: string; children?: ReactNode; action?: ReactNode }) {
  const icons = { loading: <LoaderCircle className="spin" />, empty: <Inbox />, error: <AlertCircle />, success: <CheckCircle2 /> }
  return <div className={`state state--${kind}`}>{icons[kind]}<strong>{title}</strong>{children && <p>{children}</p>}{action}</div>
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Попробуйте ещё раз'
  return <State kind="error" title="Не удалось загрузить данные" action={retry && <Button variant="secondary" onClick={retry}>Повторить</Button>}>{message}</State>
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'danger' | 'info' }) { return <span className={`badge badge--${tone}`}>{children}</span> }

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const titleId = useId()
  const dialogRef = useRef<HTMLElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const dialog = dialogRef.current
    if (dialog && !dialog.contains(document.activeElement)) {
      dialog.querySelector<HTMLElement>('input, select, textarea, button, [href]')?.focus()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeRef.current()
      }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const controls = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'))
      if (!controls.length) return
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      if (previousFocus?.isConnected) previousFocus.focus()
    }
  }, [])

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={dialogRef}>
      <div className="modal__head"><h2 id={titleId}>{title}</h2><button className="icon-button" aria-label="Закрыть" onClick={onClose}><X /></button></div>
      {children}
    </section>
  </div>
}

export function Field({ label, error, hint, children }: { label: string; error?: string; hint?: string; children: ReactNode }) {
  const descriptionId = useId()
  const description = error || hint
  const control = isValidElement<{ 'aria-label'?: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }>(children)
    ? cloneElement(children, {
      'aria-label': children.props['aria-label'] ?? label,
      'aria-describedby': [children.props['aria-describedby'], description ? descriptionId : undefined].filter(Boolean).join(' ') || undefined,
      'aria-invalid': error ? true : children.props['aria-invalid'],
    })
    : children
  return <label className="field"><span>{label}</span>{control}{description && <small id={descriptionId} role={error ? 'alert' : undefined} className={error ? 'field-error' : undefined}>{description}</small>}</label>
}

export function Progress({ value, max = 100, tone = 'green' }: { value: number; max?: number; tone?: string }) {
  const percent = max > 0 ? Math.max(0, Math.min(100, value / max * 100)) : 0
  return <div className="progress" aria-label={`${Math.round(percent)}%`}><div style={{ width: `${percent}%`, background: tone }} /></div>
}
