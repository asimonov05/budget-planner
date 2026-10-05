import { ArrowUpRight, Sparkles, X } from 'lucide-react'
import './release-preview-popup.css'

export interface ReleasePreview {
  id: number
  kind: 'release'
  title: string
  body: string
  release_note_id: number | null
  created_at: string
  read_at: string | null
}

export function ReleasePreviewPopup({
  preview, onOpen, onDismiss,
}: {
  preview: ReleasePreview
  onOpen: () => void
  onDismiss: () => void
}) {
  const date = new Date(preview.created_at)
  const dateLabel = Number.isNaN(date.getTime())
    ? ''
    : new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(date)

  return <section
    className="release-preview-popup"
    aria-label="Уведомление о новом релизе"
    aria-live="polite"
    onKeyDown={(event) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onDismiss()
      }
    }}
  >
    <button className="release-preview-popup__open" type="button" onClick={onOpen} aria-label={`Открыть уведомления: ${preview.title}`}>
      <span className="release-preview-popup__icon"><Sparkles aria-hidden="true"/></span>
      <span className="release-preview-popup__content">
        <span className="release-preview-popup__meta"><strong>Контур · новый релиз</strong>{dateLabel && <time dateTime={preview.created_at}>{dateLabel}</time>}</span>
        <strong className="release-preview-popup__title">{preview.title}</strong>
        <span className="release-preview-popup__summary">{preview.body}</span>
        <span className="release-preview-popup__link">Открыть уведомления <ArrowUpRight aria-hidden="true"/></span>
      </span>
    </button>
    <button className="release-preview-popup__close" type="button" onClick={onDismiss} aria-label="Закрыть превью релиза"><X aria-hidden="true"/></button>
  </section>
}
