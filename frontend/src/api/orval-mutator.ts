/** Fetch adapter used by Orval-generated operations.
 *
 * Keeping this policy in one place makes generated hooks safe for the browser:
 * cookies are included, CSRF is attached to state-changing requests, and the
 * generated response wrapper remains compatible with Orval's fetch client.
 */
export async function botqFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const method = (options.method ?? 'GET').toUpperCase()
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = document.cookie.split('; ').find((part) => part.startsWith('csrf_token='))?.split('=').slice(1).join('=')
    if (csrf) headers.set('X-CSRF-Token', decodeURIComponent(csrf))
  }
  const response = await fetch(url, { ...options, headers, credentials: 'include' })
  const text = await response.text()
  const data = text ? JSON.parse(text) as T : {} as T
  if (data && typeof data === 'object') Object.assign(data, { status: response.status, headers: response.headers })
  return data
}
