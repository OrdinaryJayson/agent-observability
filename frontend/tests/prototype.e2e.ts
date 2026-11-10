import { expect, test } from '@playwright/test'

test('create task, show trace, reload and restore the run', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', err => errors.push(err.message))
  await page.goto('/')
  await page.getByLabel('任务名称', { exact: true }).fill('浏览器成功流程')
  await page.getByRole('button', { name: '创建并执行', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Trace 调用树' })).toBeVisible()
  await expect(page.getByText('SUCCESS', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: /Model reasoning/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Model reasoning' })).toBeVisible()
  const id = await page.getByLabel('恢复查询已有 Run').inputValue()
  expect(id).toMatch(/^[0-9a-f-]{36}$/)
  await page.reload()
  await page.getByRole('button', { name: '查询 / 重试' }).click()
  await expect(page.getByRole('heading', { name: 'Trace 调用树' })).toBeVisible()
  expect(errors).toEqual([])
  await page.screenshot({ path: 'test-results/prototype-desktop.png', fullPage: true })
})

test('mobile view displays a failed run and its error event', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByLabel('生成工具失败场景').check()
  await page.getByRole('button', { name: '创建并执行', exact: true }).click()
  await expect(page.getByText('FAILED', { exact: true })).toBeVisible()
  await expect(page.getByText('tool.failed', { exact: true }).first()).toBeVisible()
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
  expect(fits).toBe(true)
  await page.screenshot({ path: 'test-results/prototype-mobile.png', fullPage: true })
})

test('API failure allows retry without creating a duplicate run', async ({ page }) => {
  await page.goto('/')
  await page.route('**/api/v1/runs/*', route => route.fulfill({
    status: 500, contentType: 'application/json',
    body: JSON.stringify({ error: { code: 'INTERNAL_ERROR', message: 'Temporary failure', details: {} } }),
  }))
  await page.getByRole('button', { name: '创建并执行', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Temporary failure')
  const id = await page.getByLabel('恢复查询已有 Run').inputValue()
  await page.unroute('**/api/v1/runs/*')
  await page.getByRole('button', { name: '查询 / 重试' }).click()
  await expect(page.getByRole('heading', { name: 'Trace 调用树' })).toBeVisible()
  expect(await page.getByLabel('恢复查询已有 Run').inputValue()).toBe(id)
})
