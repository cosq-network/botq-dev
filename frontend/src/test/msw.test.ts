import { describe, expect, it } from 'vitest'
import { api } from '../api'

describe('MSW API integration', () => {
  it('serves typed envelope responses through the centralized client', async () => {
    await expect(api<{ id: string }>('/api/v1/test-resource')).resolves.toEqual({ id: 'msw-1' })
  })
})
