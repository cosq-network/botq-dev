import { test, expect } from '@playwright/test'
import { visitAuthenticated } from './support'

test.describe('authenticated delivery workflows', () => {
  const screens: [string, string][] = [
    ['/', 'Good to see you'],
    ['/organization', 'Organization'],
    ['/projects', 'Projects'],
    ['/requirements?project=project-1', 'Requirements'],
    ['/work-items?project=project-1', 'Work items'],
    ['/architecture?project=project-1', 'Architecture'],
    ['/planning?project=project-1', 'Plans'],
    ['/design?project=project-1', 'Design'],
    ['/acceptance?project=project-1', 'Acceptance'],
    ['/gates?project=project-1', 'Gates'],
    ['/releases?project=project-1', 'Releases'],
    ['/operations', 'Operations'],
  ]

  for (const [path, heading] of screens) {
    test(`renders ${path} with authenticated workspace context`, async ({ page }) => {
      await visitAuthenticated(page, path)
      await expect(page.getByRole('heading', { name: new RegExp(heading === 'Organization' ? '(Organization|Feature unavailable)' : heading, 'i') }).first()).toBeVisible()
      if (path !== '/organization') await expect(page.getByText('Protected session')).toBeVisible()
      expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
    })
  }

  test('renders nested detail routes with domain-specific content', async ({ page }) => {
    for (const [path, text] of [['/requirements/baseline-1', 'Version history'], ['/work-items/work-1', 'Dependencies'], ['/plans/plan-1', 'Plan'], ['/agent-runs/run-1', 'Execution policy'], ['/releases/release-1', 'Readiness'], ['/deployments/deployment-1', 'Deployment detail']] as const) {
      await visitAuthenticated(page, path)
      await expect(page.getByText(text, { exact: true })).toBeVisible()
    }
  })
})
