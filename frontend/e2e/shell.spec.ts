import { expect, test } from '@playwright/test'

test('unauthenticated users are sent to login', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'botq' })).toBeVisible()
})

test('login page exposes labeled credentials and organization fields', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByLabel('Organization')).toBeVisible()
  await expect(page.getByLabel('Email')).toBeVisible()
  await expect(page.getByLabel('Password')).toBeVisible()
})
