import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { visitAuthenticated } from './support'

test.describe('major screen accessibility', () => {
  const screens = ['/', '/projects', '/requirements?project=project-1', '/work-items?project=project-1', '/architecture?project=project-1', '/planning?project=project-1', '/design?project=project-1', '/acceptance?project=project-1', '/gates?project=project-1', '/releases?project=project-1', '/operations', '/organization']
  for (const path of screens) {
    test(`has no axe violations on ${path}`, async ({ page }) => {
      await visitAuthenticated(page, path)
      const results = await new AxeBuilder({ page }).include('main').analyze()
      expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([])
    })
  }
})
