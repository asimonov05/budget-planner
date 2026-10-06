import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  COLOR_SCHEME_STORAGE_KEY,
  FONT_STORAGE_KEY,
  THEME_STORAGE_KEY,
  ThemeProvider,
  readColorScheme,
  readFontChoice,
  readThemePreference,
  resolveThemePreference,
  useTheme,
} from './theme'

const storedValues = new Map<string, string>()
const memoryStorage: Storage = {
  get length() { return storedValues.size },
  clear: () => storedValues.clear(),
  getItem: (key) => storedValues.get(key) ?? null,
  key: (index) => Array.from(storedValues.keys())[index] ?? null,
  removeItem: (key) => { storedValues.delete(key) },
  setItem: (key, value) => { storedValues.set(key, value) },
}

class MediaQueryMock {
  matches: boolean
  readonly media = '(prefers-color-scheme: dark)'
  readonly onchange = null
  private listeners = new Set<(event: MediaQueryListEvent) => void>()

  constructor(matches: boolean) {
    this.matches = matches
  }

  addEventListener = (_type: string, listener: (event: MediaQueryListEvent) => void) => {
    this.listeners.add(listener)
  }

  removeEventListener = (_type: string, listener: (event: MediaQueryListEvent) => void) => {
    this.listeners.delete(listener)
  }

  setMatches(matches: boolean) {
    this.matches = matches
    const event = { matches, media: this.media } as MediaQueryListEvent
    this.listeners.forEach((listener) => listener(event))
  }
}

function Probe() {
  const { preference, resolvedTheme, colorScheme, fontChoice, setPreference, setColorScheme, setFontChoice } = useTheme()
  return <div>
    <span data-testid="preference">{preference}</span>
    <span data-testid="resolved">{resolvedTheme}</span>
    <span data-testid="color-scheme">{colorScheme}</span>
    <span data-testid="font-choice">{fontChoice}</span>
    <button onClick={() => setPreference('dark')}>Тёмная</button>
    <button onClick={() => setPreference('system')}>Системная</button>
    <button onClick={() => setColorScheme('ocean')}>Океан</button>
    <button onClick={() => setFontChoice('golos')}>Golos Text</button>
  </div>
}

describe('theme preference', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', memoryStorage)
    window.localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    document.documentElement.removeAttribute('data-color-scheme')
    document.documentElement.removeAttribute('data-font')
    document.documentElement.style.removeProperty('color-scheme')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('accepts only known stored values and resolves system preference', () => {
    expect(readThemePreference({ getItem: () => 'dark' })).toBe('dark')
    expect(readThemePreference({ getItem: () => 'unexpected' })).toBe('system')
    expect(readColorScheme({ getItem: () => 'plum' })).toBe('plum')
    expect(readColorScheme({ getItem: () => 'contour' })).toBe('contour')
    expect(readColorScheme({ getItem: () => 'unexpected' })).toBe('contour')
    expect(readFontChoice({ getItem: () => 'golos' })).toBe('golos')
    expect(readFontChoice({ getItem: () => 'humanist' })).toBe('humanist')
    expect(readFontChoice({ getItem: () => 'book' })).toBe('book')
    expect(readFontChoice({ getItem: () => 'classic' })).toBe('classic')
    expect(readFontChoice({ getItem: () => 'system' })).toBe('system')
    expect(readFontChoice({ getItem: () => 'unexpected' })).toBe('system')
    expect(readFontChoice({ getItem: (key) => key === 'budget-planner-font' ? 'classic' : null })).toBe('system')
    expect(resolveThemePreference('system', true)).toBe('dark')
    expect(resolveThemePreference('system', false)).toBe('light')
  })

  it('applies and persists theme, color scheme and font immediately', () => {
    const media = new MediaQueryMock(false)
    vi.stubGlobal('matchMedia', vi.fn(() => media as unknown as MediaQueryList))
    render(<ThemeProvider><Probe /></ThemeProvider>)

    fireEvent.click(screen.getByRole('button', { name: 'Тёмная' }))
    fireEvent.click(screen.getByRole('button', { name: 'Океан' }))
    fireEvent.click(screen.getByRole('button', { name: 'Golos Text' }))

    expect(screen.getByTestId('preference')).toHaveTextContent('dark')
    expect(screen.getByTestId('resolved')).toHaveTextContent('dark')
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    expect(document.documentElement).toHaveAttribute('data-color-scheme', 'ocean')
    expect(document.documentElement).toHaveAttribute('data-font', 'golos')
    expect(document.documentElement.style.colorScheme).toBe('dark')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    expect(window.localStorage.getItem(COLOR_SCHEME_STORAGE_KEY)).toBe('ocean')
    expect(window.localStorage.getItem(FONT_STORAGE_KEY)).toBe('golos')
  })

  it('tracks operating-system changes only in system mode', () => {
    const media = new MediaQueryMock(false)
    vi.stubGlobal('matchMedia', vi.fn(() => media as unknown as MediaQueryList))
    render(<ThemeProvider><Probe /></ThemeProvider>)

    expect(screen.getByTestId('resolved')).toHaveTextContent('light')
    act(() => media.setMatches(true))
    expect(screen.getByTestId('resolved')).toHaveTextContent('dark')

    fireEvent.click(screen.getByRole('button', { name: 'Тёмная' }))
    act(() => media.setMatches(false))
    expect(screen.getByTestId('resolved')).toHaveTextContent('dark')

    fireEvent.click(screen.getByRole('button', { name: 'Системная' }))
    expect(screen.getByTestId('resolved')).toHaveTextContent('light')
  })
})
