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

export const THEME_STORAGE_KEY = 'budget-planner-theme'
export const COLOR_SCHEME_STORAGE_KEY = 'budget-planner-color-scheme'

const isThemePreference = (value: unknown): value is ThemePreference =>
  value === 'light' || value === 'dark' || value === 'system'

const isColorScheme = (value: unknown): value is ColorScheme =>
  value === 'forest' || value === 'ocean' || value === 'plum' || value === 'amber'

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
  document
    .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    ?.setAttribute('content', theme === 'dark' ? '#151c18' : '#f5f4ee')
}

export function applyColorScheme(colorScheme: ColorScheme) {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.colorScheme = colorScheme
}

export function initializeTheme() {
  const preference = readThemePreference()
  const colorScheme = readColorScheme()
  const resolvedTheme = resolveThemePreference(preference)
  applyResolvedTheme(resolvedTheme)
  applyColorScheme(colorScheme)
  return { preference, resolvedTheme, colorScheme }
}

interface ThemeContextValue {
  preference: ThemePreference
  resolvedTheme: ResolvedTheme
  colorScheme: ColorScheme
  setPreference: (preference: ThemePreference) => void
  setColorScheme: (colorScheme: ColorScheme) => void
}

const ThemeContext = createContext<ThemeContextValue>({
  preference: 'system',
  resolvedTheme: 'light',
  colorScheme: 'forest',
  setPreference: () => undefined,
  setColorScheme: () => undefined,
})

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readThemePreference)
  const [colorScheme, setColorSchemeState] = useState<ColorScheme>(readColorScheme)
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
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, preference)
      window.localStorage.setItem(COLOR_SCHEME_STORAGE_KEY, colorScheme)
    } catch {
      // Theme still works for this session when storage is unavailable.
    }
  }, [preference, resolvedTheme, colorScheme])

  const setPreference = useCallback((next: ThemePreference) => setPreferenceState(next), [])
  const setColorScheme = useCallback((next: ColorScheme) => setColorSchemeState(next), [])
  const value = useMemo(
    () => ({ preference, resolvedTheme, colorScheme, setPreference, setColorScheme }),
    [preference, resolvedTheme, colorScheme, setPreference, setColorScheme],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}
