import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'
export type ColorScheme = 'forest' | 'ocean' | 'plum' | 'amber'
export type FontChoice = 'classic' | 'golos' | 'humanist' | 'book'

// The colour input needs a concrete value; these match the light accent in themes.css.
export const colorSchemeAccents: Record<ColorScheme, string> = {
  forest: '#2f7354',
  ocean: '#196f7b',
  plum: '#815575',
  amber: '#9b6829',
}

export const THEME_STORAGE_KEY = 'budget-planner-theme'
export const COLOR_SCHEME_STORAGE_KEY = 'budget-planner-color-scheme'
// The previous key stored "classic" even when no font was explicitly chosen.
export const FONT_STORAGE_KEY = 'budget-planner-font-v2'

const isThemePreference = (value: unknown): value is ThemePreference =>
  value === 'light' || value === 'dark' || value === 'system'

const isColorScheme = (value: unknown): value is ColorScheme =>
  value === 'forest' || value === 'ocean' || value === 'plum' || value === 'amber'

const isFontChoice = (value: unknown): value is FontChoice =>
  value === 'classic' || value === 'golos' || value === 'humanist' || value === 'book'

function systemPrefersDark() {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function readThemePreference(
  storage?: Pick<Storage, 'getItem'>,
): ThemePreference {
  try {
    const source = storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined)
    const stored = source?.getItem(THEME_STORAGE_KEY)
    return isThemePreference(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

export function readColorScheme(
  storage?: Pick<Storage, 'getItem'>,
): ColorScheme {
  try {
    const source = storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined)
    const stored = source?.getItem(COLOR_SCHEME_STORAGE_KEY)
    return isColorScheme(stored) ? stored : 'forest'
  } catch {
    return 'forest'
  }
}

export function readFontChoice(
  storage?: Pick<Storage, 'getItem'>,
): FontChoice {
  try {
    const source = storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined)
    const stored = source?.getItem(FONT_STORAGE_KEY)
    return isFontChoice(stored) ? stored : 'golos'
  } catch {
    return 'golos'
  }
}

export function resolveThemePreference(
  preference: ThemePreference,
  prefersDark = systemPrefersDark(),
): ResolvedTheme {
  return preference === 'system' ? (prefersDark ? 'dark' : 'light') : preference
}

export function applyResolvedTheme(theme: ResolvedTheme) {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
  syncThemeColor()
}

export function applyColorScheme(colorScheme: ColorScheme) {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.colorScheme = colorScheme
  syncThemeColor()
}

function syncThemeColor() {
  const canvas = getComputedStyle(document.documentElement).getPropertyValue('--canvas').trim()
  document
    .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    ?.setAttribute('content', canvas || (document.documentElement.dataset.theme === 'dark' ? '#111c16' : '#f4f7f3'))
}

export function applyFontChoice(fontChoice: FontChoice) {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.font = fontChoice
}

export function initializeTheme() {
  const preference = readThemePreference()
  const colorScheme = readColorScheme()
  const fontChoice = readFontChoice()
  const resolvedTheme = resolveThemePreference(preference)
  applyResolvedTheme(resolvedTheme)
  applyColorScheme(colorScheme)
  applyFontChoice(fontChoice)
  return { preference, resolvedTheme, colorScheme, fontChoice }
}

interface ThemeContextValue {
  preference: ThemePreference
  resolvedTheme: ResolvedTheme
  colorScheme: ColorScheme
  fontChoice: FontChoice
  setPreference: (preference: ThemePreference) => void
  setColorScheme: (colorScheme: ColorScheme) => void
  setFontChoice: (fontChoice: FontChoice) => void
}

const ThemeContext = createContext<ThemeContextValue>({
  preference: 'system',
  resolvedTheme: 'light',
  colorScheme: 'forest',
  fontChoice: 'golos',
  setPreference: () => undefined,
  setColorScheme: () => undefined,
  setFontChoice: () => undefined,
})

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readThemePreference)
  const [colorScheme, setColorSchemeState] = useState<ColorScheme>(readColorScheme)
  const [fontChoice, setFontChoiceState] = useState<FontChoice>(readFontChoice)
  const [prefersDark, setPrefersDark] = useState(systemPrefersDark)
  const resolvedTheme = resolveThemePreference(preference, prefersDark)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const update = (event: MediaQueryListEvent | MediaQueryList) => setPrefersDark(event.matches)
    update(media)
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', update)
      return () => media.removeEventListener('change', update)
    }
    media.addListener(update)
    return () => media.removeListener(update)
  }, [])

  useLayoutEffect(() => {
    applyResolvedTheme(resolvedTheme)
    applyColorScheme(colorScheme)
    applyFontChoice(fontChoice)
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, preference)
      window.localStorage.setItem(COLOR_SCHEME_STORAGE_KEY, colorScheme)
      window.localStorage.setItem(FONT_STORAGE_KEY, fontChoice)
    } catch {
      // Theme still works for this session when storage is unavailable.
    }
  }, [preference, resolvedTheme, colorScheme, fontChoice])

  const setPreference = useCallback((next: ThemePreference) => setPreferenceState(next), [])
  const setColorScheme = useCallback((next: ColorScheme) => setColorSchemeState(next), [])
  const setFontChoice = useCallback((next: FontChoice) => setFontChoiceState(next), [])
  const value = useMemo(
    () => ({ preference, resolvedTheme, colorScheme, fontChoice, setPreference, setColorScheme, setFontChoice }),
    [preference, resolvedTheme, colorScheme, fontChoice, setPreference, setColorScheme, setFontChoice],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}
