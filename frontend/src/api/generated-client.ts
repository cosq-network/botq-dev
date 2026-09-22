import createClient from 'openapi-fetch'
import type { paths } from './generated'

function csrfToken() {
  return document.cookie.split('; ').find((part) => part.startsWith('csrf_token='))?.split('=').slice(1).join('=')
}

export const generatedClient = createClient<paths>({ baseUrl: '' })
generatedClient.use({
  onRequest({ request }) {
    const next = new Request(request, { credentials: 'include' })
    const token = csrfToken()
    if (token && !['GET', 'HEAD', 'OPTIONS'].includes(next.method.toUpperCase())) next.headers.set('X-CSRF-Token', decodeURIComponent(token))
    next.headers.set('Accept', 'application/json')
    return next
  },
})
