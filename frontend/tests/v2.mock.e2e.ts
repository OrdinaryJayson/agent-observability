import { expect, test, type Page, type Route } from '@playwright/test'
import { join } from 'node:path'
import fixtures from '../../contracts/v2/examples.json' with { type: 'json' }
import v1 from '../../contracts/v1-http-examples.json' with { type: 'json' }

const ids = fixtures.ids
const second = fixtures.comparison.run_ids[1]
const stage = (kind: string, id: string) => `/#/${kind}?id=${id}`
const trace = `/#/analysis?run=${ids.run_id}`
async function capture(page: Page, filename: string) {
  if (process.env.V2_SCREENSHOT_DIR) await page.screenshot({ path: join(process.env.V2_SCREENSHOT_DIR, filename), fullPage: true })
}
function envelope(data: unknown) { return { data, message: 'success' } }
function pageOf(data: unknown[], cursor: string | null = null) {
  return { data, meta: { limit: 50, next_cursor: cursor, has_more: !!cursor } }
}
type Override = (path: string, method: string, url: URL, route: Route) => Promise<boolean | undefined> | boolean | undefined
async function mock(page: Page, override?: Override) {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const example = v1.endpoints.find(item => item.path === path && item.method === route.request().method())
    await route.fulfill(example ? { status: example.status, json: example.response } : { status: 404, json: v1.error })
  })
  await page.route('**/api/v2/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname.slice('/api/v2'.length)
    const method = route.request().method()
    if (await override?.(path, method, url, route)) return
    const paths: Record<string, unknown> = {
      '/overview': envelope(fixtures.overview),
      '/workflows': pageOf([fixtures.workflow]),
      ['/workflows/' + ids.workflow_id]: envelope(fixtures.workflow),
      ['/workflows/' + ids.workflow_id + '/versions']: pageOf([fixtures.version]),
      ['/workflow-versions/' + ids.version_id]: envelope(fixtures.version),
      '/runs': pageOf([fixtures.run, { ...fixtures.run, run_id: second }]),
      ['/runs/' + ids.run_id]: envelope(fixtures.run),
      ['/runs/' + ids.run_id + '/snapshot']: envelope(fixtures.snapshot),
      ['/runs/' + ids.run_id + '/analysis']: envelope(fixtures.analysis),
      '/comparisons': envelope(fixtures.comparison),
      '/search/spans': pageOf([{ ...fixtures.snapshot.spans[0], run_id: ids.run_id, task_id: ids.task_id, trace_id: fixtures.run.trace_id }]),
      '/search/events': pageOf([{ ...fixtures.journal.find(item => item.kind === 'span.event')!.payload, run_id: ids.run_id, task_id: ids.task_id, trace_id: fixtures.run.trace_id }]),
      '/analytics/series': envelope([{ date: '2026-11-16', total_runs: 1 }]),
      '/analytics/aggregate-status': envelope(fixtures.aggregate_status),
      '/analytics/refresh': envelope(fixtures.aggregate_status),
      '/datasets': pageOf([fixtures.dataset]),
      ['/datasets/' + ids.dataset_id]: envelope(fixtures.dataset),
      '/experiments': pageOf([fixtures.experiment_results[0].experiment]),
      '/database/catalog': envelope({ tables: [{ name: 'runs', columns: [], indexes: [], constraints: [], size_bytes: 0 }], views: [] }),
      '/database/query-templates': envelope([]),
      '/audit': pageOf([{ audit_id: 1, action: 'PUBLISH', resource_type: 'workflow', resource_id: ids.workflow_id }]),
    }
    if (path === '/runs/' + ids.run_id + '/journal') {
      const after = Number(url.searchParams.get('after_seq'))
      const records = fixtures.journal.filter(item => item.seq > after)
      await route.fulfill({ json: { data: records, meta: { next_after_seq: 25, has_more: false, snapshot_seq: 25 } } })
    } else {
      await route.fulfill(path in paths ? { json: paths[path] } : { status: 404, json: { error: { message: '未登记的测试请求 ' + path } } })
    }
  })
}
function sse(record: (typeof fixtures.journal)[number]) {
  return `id: ${record.seq}\r\nevent: ${record.kind}\r\ndata: ${JSON.stringify(record)}\r\n\r\n`
}

test('首页、全部主导航以及移动端直达', async ({ page }) => {
  const jsErrors: string[] = []
  page.on('pageerror', error => jsErrors.push(error.message))
  await mock(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '运行总览', exact: true })).toBeVisible()
  await expect(page.getByText('P95 执行耗时')).toBeVisible()
  await capture(page, 'agent-v2-overview-mobile.png')
  for (const label of ['工作流', '运行中心', '轨迹分析', '日志检索', '运行对比', '数据库实验', '数据与设计']) {
    await page.getByRole('link', { name: label, exact: true }).click()
    await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await page.getByRole('link', { name: '快速执行', exact: true }).click()
  await expect(page.getByRole('button', { name: '创建并执行' })).toBeVisible()
  expect(jsErrors).toEqual([])
})

test('工作流编辑、412 冲突保留编辑、422、校验定位和带 If-Match 发布', async ({ page }) => {
  let saves = 0
  let validations = 0
  let stored = structuredClone(fixtures.workflow)
  await mock(page, async (path, method, _url, route) => {
    if (path === '/workflows/' + ids.workflow_id && method === 'GET') {
      await route.fulfill({ json: envelope(stored) }); return true
    }
    if (path === '/workflows/' + ids.workflow_id && method === 'PATCH') {
      expect(route.request().headers()['if-match']).toBe(`"${stored.revision}"`)
      const body = route.request().postDataJSON()
      saves++
      if (saves === 1) {
        stored.revision++
        await route.fulfill({ status: 412, json: fixtures.errors['412'] }); return true
      }
      if (saves === 2) {
        await route.fulfill({ status: 422, json: fixtures.errors['422'] }); return true
      }
      stored = { ...stored, ...body, revision: stored.revision + 1 }
      await route.fulfill({ json: envelope(stored) }); return true
    }
    if (path.endsWith('/validate')) {
      await route.fulfill({ json: envelope(++validations > 1 ? fixtures.validation : { valid: false, errors: [{
        code: 'WORKFLOW_INVALID', node_key: 'search_a', edge_index: null, path: '/nodes/1', message: '校验样例',
      }] }) }); return true
    }
    if (path.endsWith('/versions') && method === 'POST') {
      expect(route.request().headers()['if-match']).toBe(`"${stored.revision}"`)
      expect(route.request().postDataJSON().expected_definition_hash).toBe(fixtures.version.definition_hash)
      await route.fulfill({ status: 201, json: envelope(fixtures.version) }); return true
    }
  })
  await page.goto(stage('workflows', ids.workflow_id))
  await expect(page.locator('.graph-node')).toHaveCount(fixtures.workflow.draft.nodes.length)
  await page.getByLabel('工作流名称').fill('本地编辑')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText(/草稿已被其他人更新/)).toBeVisible()
  await expect(page.getByLabel('工作流名称')).toHaveValue('本地编辑')
  await page.getByRole('button', { name: '载入服务器草稿' }).click()
  await expect(page.getByLabel('工作流名称')).toHaveValue(stored.name)
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText('草稿已保存。')).toBeVisible()
  await page.getByRole('button', { name: '校验草稿' }).click()
  await page.getByRole('button', { name: /WORKFLOW_INVALID/ }).click()
  await expect(page.locator('#workflow-node-editor')).toBeFocused()
  await expect(page.getByRole('button', { name: '发布已保存草稿' })).toBeDisabled()
  await page.getByRole('button', { name: '校验草稿' }).click()
  await expect(page.getByText('工作流语义校验通过。')).toBeVisible()
  await page.getByRole('button', { name: '发布已保存草稿' }).click()
  await expect(page.getByRole('heading', { name: /版本 1 · 只读/ })).toBeVisible()
  await page.getByRole('button', { name: '复制版本为新草稿' }).click()
  await expect(page.getByLabel('工作流名称')).toHaveValue('工作流副本')
})

test('运行丢 ACK 后带相同键与参数重试，取消与完成竞态可读', async ({ page }) => {
  const submissions: { key: string; body: unknown }[] = []
  await mock(page, async (path, method, _url, route) => {
    if (path === '/runs' && method === 'GET') {
      await route.fulfill({ json: pageOf([fixtures.running_snapshot.run]) }); return true
    }
    if (path.endsWith('/cancel')) {
      await route.fulfill({ json: envelope({ accepted: false, already_terminal: true, run: fixtures.run }) }); return true
    }
    if (path.startsWith('/tasks/') && path.endsWith('/runs')) {
      submissions.push({ key: route.request().headers()['idempotency-key'], body: route.request().postDataJSON() })
      if (submissions.length === 1) await route.abort('failed')
      else if (submissions.length === 2) await route.fulfill({ status: 409, json: fixtures.errors['409'] })
      else await route.fulfill({ status: 202, json: fixtures.accepted })
      return true
    }
  })
  await page.goto('/#/run-center?version=' + ids.version_id)
  await page.getByRole('button', { name: '取消运行' }).click()
  await expect(page.getByText('运行已先进入终态。')).toBeVisible()
  await page.getByLabel('选择 Task').selectOption({ label: '联调样例' })
  await page.getByLabel('无绑定模拟').check()
  await page.getByRole('button', { name: '提交运行', exact: true }).click()
  await expect(page.getByRole('button', { name: '重试同一次提交' })).toBeEnabled()
  await page.reload()
  await page.getByRole('button', { name: '重试同一次提交' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await page.getByRole('button', { name: '重试同一次提交' }).click()
  await expect(page).toHaveURL(/#\/analysis\?run=/)
  expect(submissions[0].key).toMatch(/^[A-Za-z0-9_-]{8,100}$/)
  expect(submissions[0]).toEqual(submissions[1])
  expect(submissions[1]).toEqual(submissions[2])
})

test('SSE 重复、跳号、断线和 410 后从水位恢复，回放可定位', async ({ page }) => {
  let connections = 0
  let snapshots = 0
  const cursors: string[] = []
  const journal = fixtures.journal
  await mock(page, async (path, _method, url, route) => {
    if (path.endsWith('/snapshot')) {
      snapshots++
      await route.fulfill({ json: envelope(connections >= 3 ? fixtures.snapshot : fixtures.running_snapshot) }); return true
    }
    if (path.endsWith('/stream')) {
      connections++
      const after = Number(url.searchParams.get('after_seq'))
      cursors.push(String(after))
      if (connections === 2) await route.fulfill({ status: 410, json: fixtures.errors['410'] })
      else {
        const event = journal.find(item => item.seq === after + 2)!
        const duplicate = journal.find(item => item.seq === after)!
        const last = journal.at(-1)!
        await route.fulfill({ contentType: 'text/event-stream', body: connections === 1
          ? sse(duplicate) + sse(event) + 'event: stream.error\n\ndata: {}\n\n'
          : sse(last) })
      }
      return true
    }
  })
  await page.goto(trace)
  await expect(page.locator('.v2-run-summary')).toContainText('已结束 · seq 25')
  await page.setViewportSize({ width: 1440, height: 900 })
  await capture(page, 'agent-v2-trace-desktop.png')
  expect(cursors).toEqual(['8', '10', '8'])
  expect(snapshots).toBe(3)
  await page.getByRole('button', { name: '事件 / 回放' }).click()
  await expect(page.locator('.v2-scroll tbody tr')).toHaveCount(25)
  await page.getByRole('button', { name: '10', exact: true }).click()
  await expect(page.getByLabel('节点和 Span 详情')).toBeVisible()
  await page.getByRole('button', { name: '时间瀑布' }).click()
  await expect(page.locator('.waterfall-axis')).toBeVisible()
  await page.getByRole('button', { name: '耗时分析' }).click()
  await expect(page.getByText('理论关键路径', { exact: true })).toBeVisible()
})

test('拓扑显示 50 节点并保留 500 Span，LEGACY 切换为静态详情', async ({ page }) => {
  const definition = structuredClone(fixtures.version.definition)
  definition.nodes = Array.from({ length: 50 }, (_, index) => ({
    ...definition.nodes[0], node_key: 'n' + index, name: '节点 ' + index,
  }))
  definition.edges = Array.from({ length: 49 }, (_, index) => ({ source: 'n' + index, target: 'n' + (index + 1), route: 'ALWAYS' as const }))
  const spans = Array.from({ length: 500 }, (_, index) => ({
    ...fixtures.snapshot.spans[0], span_id: (index + 1).toString(16).padStart(16, '0'), span_name: 'Span ' + index,
    parent_span_id: index ? '0000000000000001' : null, node_key: index ? 'n' + index % 50 : null,
  }))
  let legacy = false
  await mock(page, async (path, _method, _url, route) => {
    if (path === '/runs/' + ids.run_id && legacy) {
      await route.fulfill({ json: envelope({ ...fixtures.run, mode: 'LEGACY', version_id: null }) }); return true
    }
    if (path.startsWith('/workflow-versions/')) {
      await route.fulfill({ json: envelope({ ...fixtures.version, definition }) }); return true
    }
    if (path.endsWith('/snapshot')) {
      await route.fulfill({ json: envelope({ ...fixtures.snapshot, spans, seq: 0, run: { ...fixtures.run, span_count: 500, last_seq: 0 } }) }); return true
    }
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(trace)
  await expect(page.locator('.graph-node')).toHaveCount(50)
  await page.getByRole('button', { name: 'Span 归属树' }).click()
  await expect(page.locator('.graph-node')).toHaveCount(500)
  await page.getByLabel('搜索节点').fill('Span 499')
  await page.getByRole('button', { name: '定位', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'n49', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  legacy = true
  await page.reload()
  await expect(page.getByText(/LEGACY · 静态轨迹/)).toBeVisible()
  await expect(page.getByRole('button', { name: '事件 / 回放' })).toHaveCount(0)
})

test('检索游标与分享条件，以及同版本运行对比', async ({ page }) => {
  const seen: string[] = []
  const log = fixtures.journal.find(item => item.kind === 'span.event')!
  await mock(page, async (path, _method, url, route) => {
    if (path === '/search/events') {
      seen.push(url.search)
      await route.fulfill({ json: pageOf([{ ...log.payload, run_id: ids.run_id }], url.searchParams.get('cursor') ? null : 'opaque-token') })
      return true
    }
  })
  await page.goto('/#/search')
  await page.getByLabel('Run ID').fill(ids.run_id)
  await page.getByRole('button', { name: '检索', exact: true }).click()
  await expect(page).toHaveURL(/run_id=/)
  await page.getByRole('button', { name: '下一页' }).click()
  expect(seen.at(-1)).toContain('cursor=opaque-token')
  expect(seen.at(-1)).toContain('run_id=' + ids.run_id)
  await page.reload()
  await expect(page.getByLabel('Run ID')).toHaveValue(ids.run_id)
  await page.getByRole('link', { name: '定位轨迹' }).click()
  await expect(page.getByLabel('节点和 Span 详情')).toBeVisible()
  await page.getByRole('link', { name: '运行对比', exact: true }).click()
  await page.getByLabel('选择 ' + ids.run_id).check()
  await page.getByLabel('选择 ' + second).check()
  await page.getByRole('button', { name: '比较 2 个 Run' }).click()
  await expect(page.getByRole('heading', { name: '对比结果 · REALTIME' })).toBeVisible()
})

test('六类实验保持冻结参数，查看样本和导出，数据目录及审计可访问', async ({ page }) => {
  let index = 0
  const submitted: unknown[] = []
  const baseline = fixtures.experiment_results[0].experiment
  const alternative = {
    ...baseline, experiment_id: '77777777-7777-4777-8777-777777777778',
    config: { ...baseline.config, parameters: { query: 'TRACE', selectivity: 0.1 } },
  }
  await mock(page, async (path, method, url, route) => {
    const result = fixtures.experiment_results[index]
    if (path === '/experiments' && method === 'POST') {
      submitted.push(route.request().postDataJSON())
      expect(route.request().headers()['idempotency-key']).toBeTruthy()
      await route.fulfill({ status: 202, json: envelope(result.experiment) }); return true
    }
    if (path === '/experiments' && method === 'GET') {
      await route.fulfill({ json: pageOf([baseline, alternative]) }); return true
    }
    if (path === '/experiments/' + result.experiment.experiment_id) {
      await route.fulfill({ json: envelope(result.experiment) }); return true
    }
    if (path.endsWith('/trials')) { await route.fulfill({ json: pageOf(result.trials) }); return true }
    if (path.endsWith('/samples')) {
      await route.fulfill({ json: pageOf(result.samples.filter(row => row.trial_id === url.searchParams.get('trial_id'))) }); return true
    }
    if (path.endsWith('/export')) { await route.fulfill({ contentType: 'text/csv', body: 'sample\n' }); return true }
  })
  for (const [i, request] of fixtures.experiment_requests.entries()) {
    index = i
    await page.goto('/#/experiments')
    await page.getByLabel('数据集', { exact: true }).selectOption(ids.dataset_id)
    await page.getByLabel('案例', { exact: true }).selectOption(request.case_code)
    await page.getByRole('button', { name: '提交实验' }).click()
    await expect(page.getByRole('heading', { name: '方案结果' })).toBeVisible()
    await page.getByRole('button', { name: resultVariant(i), exact: true }).click()
    await page.getByRole('button', { name: '样本 0', exact: true }).click()
    await expect(page.getByText('全部指标与正确性证据')).toBeVisible()
  }
  expect(submitted).toEqual(fixtures.experiment_requests)
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出 CSV' }).click()
  expect((await download).suggestedFilename()).toMatch(/\.csv$/)
  index = 0
  await page.goto('/#/experiments')
  await page.getByText('对比历史实验参数', { exact: true }).click()
  await page.getByLabel(new RegExp(baseline.experiment_id)).check()
  await page.getByLabel(new RegExp(alternative.experiment_id)).check()
  await page.getByRole('button', { name: '读取方案并对比' }).click()
  await page.getByLabel('横轴').selectOption('selectivity')
  await expect(page.locator('.v2-sweep-point')).toHaveCount(6)
  await page.goto('/#/data')
  await page.getByRole('button', { name: '数据库结构' }).click()
  await expect(page.getByRole('heading', { name: /^runs\b/ })).toBeVisible()
  await page.getByRole('button', { name: '操作审计' }).click()
  await expect(page.getByRole('cell', { name: 'PUBLISH' })).toBeVisible()
})

function resultVariant(index: number) { return fixtures.experiment_results[index].trials[0].variant }
