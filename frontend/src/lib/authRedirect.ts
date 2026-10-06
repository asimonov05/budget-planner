/** Return only to photo-access on the same origin in the combined app. */
export function photoReturnPath(search: string, basePath = import.meta.env.BASE_URL): string | null {
  if (basePath !== '/budget/') return null
  const next = new URLSearchParams(search).get('next')
  if (!next) return null
  try {
    const url = new URL(next, window.location.origin)
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/photo/')) return null
    return `${url.pathname}${url.search}${url.hash}`
  } catch {
    return null
  }
}
