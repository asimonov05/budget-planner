export interface MenuPreferences {
  order: string[]
  hidden: string[]
}

const STORAGE_PREFIX = 'budget-planner-menu-v1'

export function menuStorageKey(owner: string) {
  return `${STORAGE_PREFIX}:${owner}`
}

export function defaultMenuPreferences(paths: readonly string[]): MenuPreferences {
  return { order: [...paths], hidden: [] }
}

export function normalizeMenuPreferences(value: unknown, paths: readonly string[]): MenuPreferences {
  const stored = value && typeof value === 'object' ? value as Partial<MenuPreferences> : {}
  const known = new Set(paths)
  const order = Array.isArray(stored.order)
    ? [...new Set(stored.order.filter((path): path is string => typeof path === 'string' && known.has(path)))]
    : []
  const ordered = [...order, ...paths.filter((path) => !order.includes(path))]
  const hidden = Array.isArray(stored.hidden)
    ? [...new Set(stored.hidden.filter((path): path is string => typeof path === 'string' && known.has(path)))]
    : []
  return { order: ordered, hidden }
}

export function readMenuPreferences(owner: string | null, paths: readonly string[]): MenuPreferences {
  if (!owner) return defaultMenuPreferences(paths)
  try {
    const stored = window.localStorage.getItem(menuStorageKey(owner))
    return stored ? normalizeMenuPreferences(JSON.parse(stored), paths) : defaultMenuPreferences(paths)
  } catch {
    return defaultMenuPreferences(paths)
  }
}

export function saveMenuPreferences(owner: string | null, preferences: MenuPreferences): boolean {
  if (!owner) return false
  try {
    window.localStorage.setItem(menuStorageKey(owner), JSON.stringify(preferences))
    return true
  } catch {
    return false
  }
}

export function moveMenuItem(order: readonly string[], source: string, target: string): string[] {
  const from = order.indexOf(source)
  const to = order.indexOf(target)
  if (from < 0 || to < 0 || from === to) return [...order]
  const next = [...order]
  next.splice(from, 1)
  next.splice(to, 0, source)
  return next
}
