import { describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '../api'

describe('API client', () => {
  it('adds credentials and parses the envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, data: { id: '1' }, correlation_id: 'c' }), { status: 200 })))
    await expect(api<{ id: string }>('/api/v1/example')).resolves.toEqual({ id: '1' })
    expect(fetch).toHaveBeenCalledWith('/api/v1/example', expect.objectContaining({ credentials: 'include' }))
  })

  it('normalizes API errors without leaking response bodies', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: false, correlation_id: 'c', error: { code: 'forbidden', message: 'Denied' } }), { status: 403 })))
    await expect(api('/api/v1/example')).rejects.toMatchObject({ status: 403, code: 'forbidden' } satisfies Partial<ApiError>)
  })
})
