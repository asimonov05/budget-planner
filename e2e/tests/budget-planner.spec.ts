import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'

const username = process.env.E2E_USERNAME?.trim()
const password = process.env.E2E_PASSWORD
const hasCredentials = Boolean(username && password)

async function logIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Логин').fill(username!)
  await page.getByLabel('Пароль').fill(password!)
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('navigation', { name: 'Основное меню' })).toBeAttached()
}

async function expectNoPageOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewportWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
  }))

  expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth)
}

test('an unauthenticated visitor is redirected to the login screen', async ({ page }) => {
  await page.goto('/')

  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Вход в бюджет' })).toBeVisible()
  await expect(page.getByLabel('Логин')).toBeVisible()
  await expect(page.getByLabel('Пароль')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Войти' })).toBeEnabled()
})

test('the login screen fits a 360px viewport', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await page.goto('/')

  await expect(page).toHaveURL(/\/login$/)
  await expect(page.locator('.login-intro')).toBeHidden()
  await expect(page.getByRole('heading', { name: 'Вход в бюджет' })).toBeVisible()
  await expectNoPageOverflow(page)
})

test.describe('authenticated smoke tests', () => {
  test.skip(!hasCredentials, 'Set both E2E_USERNAME and E2E_PASSWORD to run authenticated tests')

  test('a user can sign in and open the yearly plan', async ({ page }) => {
    await logIn(page)

    await expect(page.getByRole('link', { name: 'Обзор', exact: true })).toBeVisible()
    await page.getByRole('link', { name: 'План', exact: true }).click()
    await expect(page).toHaveURL(/\/plan$/)
    await expect(page.getByRole('heading', { name: 'План на год' })).toBeVisible()
  })

  test('the authenticated shell exposes mobile navigation at 360px', async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 800 })
    await logIn(page)

    await expect(page.locator('.mobile-bar')).toBeVisible()
    await expectNoPageOverflow(page)

    await page.locator('.mobile-bar .icon-button').click()
    await expect(page.locator('.sidebar')).toHaveClass(/is-open/)
    await expect(page.getByRole('navigation', { name: 'Основное меню' })).toBeVisible()
  })

  test('the bank PDF skill opens and downloads its Markdown from the import guide', async ({ page }) => {
    await logIn(page)
    await page.goto('/exchange')
    const popupPromise = page.waitForEvent('popup')
    await page.getByRole('link', { name: 'Открыть скилл' }).click()
    const popup = await popupPromise
    await expect(popup.locator('body')).toContainText('name: bank-pdf-to-budget-csv')
    await popup.close()

    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('link', { name: 'Скачать SKILL.md' }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe('bank-pdf-to-budget-csv-SKILL.md')
    expect(await download.failure()).toBeNull()
    const expected = await readFile(new URL('../../frontend/public/skills/bank-pdf-to-budget-csv/SKILL.md', import.meta.url))
    expect(await readFile((await download.path())!)).toEqual(expected)
  })
})
