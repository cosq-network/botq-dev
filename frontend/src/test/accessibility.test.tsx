import { run as axeRun } from 'axe-core'
import { expect, test, vi } from 'vitest'

test('login surface has no automated accessibility violations', async () => {
  vi.stubGlobal('fetch', vi.fn())
  document.body.innerHTML = '<main><h1>botq</h1><form aria-label="Sign in"><label for="email">Email</label><input id="email" type="email"/><label for="password">Password</label><input id="password" type="password"/><button type="submit">Sign in</button></form></main>'
  const result = await axeRun(document.body)
  expect(result.violations).toEqual([])
})
