import { expect, type Page } from '@playwright/test'

const session = {
  user: { id: 'user-1', email: 'reviewer@example.test', display_name: 'Review User', roles: ['admin'] },
  scopes: ['*'],
  organization: { id: 'org-1', name: 'Example Org', slug: 'example' },
}

export async function mockAuthenticatedApi(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path.endsWith('/auth/me')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: session, correlation_id: 'e2e-auth' }) })
    if (path.endsWith('/organizations/me')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { id: 'org-1', name: 'Example Org', slug: 'example', settings: {} }, correlation_id: 'e2e-org' }) })
    if (path.endsWith('/versions') || path.includes('/dependencies') || path.endsWith('/analyses')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: [], correlation_id: 'e2e-list' }) })
    if (path.endsWith('/projects') && route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: [{ id: 'project-1', name: 'Demo project', key: 'DEMO', lifecycle_state: 'active', default_branch: 'main', archived: false }], correlation_id: 'e2e-projects' }) })
    if (path.includes('/health/')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { status: path.includes('ready') ? 'ready' : 'ok' }, correlation_id: 'e2e-health' }) })
    if (path.includes('/projects/project-1')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { id: 'project-1', name: 'Demo project', key: 'DEMO', lifecycle_state: 'active', default_branch: 'main', archived: false, repository: { status: 'connected' } }, correlation_id: 'e2e-project' }) })
    if (path.includes('/releases/')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { id: 'release-1', version: '1.0.0', status: 'ready', commit_sha: 'abc123', readiness: { passed: true, blocking: [] }, package: {} }, correlation_id: 'e2e-release' }) })
    if (path.includes('/deployments/')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { id: 'deployment-1', release_id: 'release-1', environment: 'staging', status: 'succeeded', provider: 'local', provider_deployment_id: 'provider-1' }, correlation_id: 'e2e-deployment' }) })
    if (path.includes('/baselines/')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { id: 'baseline-1', title: 'Baseline', status: 'approved', current_version: 1, content_hash: 'hash', content: {}, version_count: 1 }, correlation_id: 'e2e-baseline' }) })
    if (path.includes('/work-items/')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { id: 'work-1', code: 'DEMO-1', kind: 'task', title: 'Task', status: 'open', priority: 'medium', risk: 'low', description: 'Task detail' }, correlation_id: 'e2e-work-item' }) })
    if (path.includes('/plans/')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { id: 'plan-1', title: 'Plan', status: 'approved', current_version: 1, content: {} }, correlation_id: 'e2e-plan' }) })
    if (path.includes('/agent-runs/')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { id: 'run-1', objective: 'Run', status: 'completed', plan_version: 1, budget: {}, allowed_tools: [], writable_paths: [] }, correlation_id: 'e2e-run' }) })
    if (path.includes('/api/v1/')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: [], correlation_id: 'e2e-empty' }) })
    return route.continue()
  })
}

export async function visitAuthenticated(page: Page, path: string) {
  await mockAuthenticatedApi(page)
  await page.goto(path)
  await expect(page.locator('main')).toBeVisible()
}
