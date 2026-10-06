import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { Modal } from './ui'

function ModalHarness() {
  const [open, setOpen] = useState(false)
  return <>
    <button onClick={() => setOpen(true)}>Открыть настройки</button>
    {open && <Modal title="Настройки" onClose={() => setOpen(false)}>
      <input aria-label="Название" />
    </Modal>}
  </>
}

describe('Modal keyboard navigation', () => {
  it('keeps focus inside and returns it to the opener after Escape', () => {
    render(<ModalHarness />)
    const opener = screen.getByRole('button', { name: 'Открыть настройки' })
    opener.focus()
    fireEvent.click(opener)

    const close = screen.getByRole('button', { name: 'Закрыть' })
    const input = screen.getByRole('textbox', { name: 'Название' })
    expect(close).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(input).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(close).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })
})
