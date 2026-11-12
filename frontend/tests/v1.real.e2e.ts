import { expect, test } from '@playwright/test'

const backend = process.env.V1_E2E_API_URL || 'http://127.0.0.1:8101/api/v1'

test('v1 real frontend, backend, simulator and PostgreSQL workflow', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const stamp = Date.now().toString()
  const names = [`Research ${stamp}`, `Analysis ${stamp}`, `Review ${stamp}`]
  const ids: string[] = []
  for (const [index, name] of names.entries()) {
    const result = await request.post(`${backend}/agents`, { data: { name, role: `role-${index}` } })
    expect(result.status()).toBe(201)
    ids.push((await result.json()).data.agent_id)
  }

  await page.goto('/#/agents')
  await page.getByRole('button', { name: `查看 ${names[0]}` }).click()
  await page.getByRole('button', { name: '编辑 Agent' }).click()
  await page.getByLabel('模型提供商').fill('integration-test')
  await page.getByRole('button', { name: '保存 Agent' }).click()
  await expect(page.getByText('已保存修改。')).toBeVisible()

  await page.goto('/#/tasks')
  await page.getByRole('button', { name: '新建任务' }).click()
  await page.getByLabel('任务名称').fill(`集成任务 ${stamp}`)
  await page.getByRole('button', { name: '创建任务' }).click()
  await expect(page.getByRole('heading', { name: '任务详情' })).toBeVisible()
  await page.getByLabel('绑定已启用的 Agent').check()
  for (const name of names) await page.getByLabel(name).check()
  await page.getByLabel('最少 Span 数').fill('105')
  await page.getByLabel('最多 Span 数').fill('105')
  await page.getByLabel('失败率（0–1）').fill('0')
  const accepted = page.waitForResponse(response => response.url().includes('/runs') && response.request().method() === 'POST' && response.status() === 202)
  await page.getByRole('button', { name: '启动模拟 Run' }).click()
  const runId = (await (await accepted).json()).data.run_id as string
  await expect(page.getByRole('heading', { name: 'Trace 调用树' })).toBeVisible({ timeout: 30000 })
  await expect(page.getByText('105 个 Span', { exact: false }).first()).toBeVisible()
  const run = (await (await request.get(`${backend}/runs/${runId}`)).json()).data
  expect(run.status).toBe('SUCCESS')
  const stats = await (await request.get(`${backend}/analytics/agents?page_size=100`)).json()
  for (const id of ids) expect(stats.data.find((row: { agent_id: string }) => row.agent_id === id)?.span_count).toBeGreaterThan(0)

  await page.goto('/#/logs')
  await page.getByLabel('Run ID').fill(run.run_id)
  await page.getByRole('button', { name: '筛选日志', exact: true }).click()
  await page.getByRole('link', { name: '定位 Trace' }).first().click()
  await expect(page.getByRole('heading', { name: 'Trace 调用树' })).toBeVisible({ timeout: 30000 })

  await page.goto('/#/overview')
  await expect(page.getByText('总运行数', { exact: true })).toBeVisible()
  await expect(page.getByText('P95 耗时', { exact: true })).toBeVisible()
  await page.goto('/#/performance')
  await expect(page.getByRole('row').filter({ hasText: names[0] })).toBeVisible()

  await page.goto('/#/benchmarks')
  for (const code of ['TRACE_QUERY_INDEX', 'ERROR_PARTIAL_INDEX']) {
    await page.getByLabel('实验案例').selectOption(code)
    await page.getByLabel('数据规模（Span 行）').selectOption('1000')
    await page.getByRole('button', { name: '运行实验', exact: true }).click()
    await expect(page.getByRole('heading', { name: '实验结果' })).toBeVisible({ timeout: 30000 })
    await expect(page.getByRole('button', { name: '运行实验', exact: true })).toBeEnabled()
  }
  await page.reload()
  await expect(page.getByRole('button', { name: '查看执行计划' }).first()).toBeVisible()
  expect(errors).toEqual([])
})
