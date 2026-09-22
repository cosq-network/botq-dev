import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

export const server = setupServer(
  http.get('/api/v1/test-resource', () => HttpResponse.json({ ok: true, correlation_id: 'msw', data: { id: 'msw-1' } })),
)
