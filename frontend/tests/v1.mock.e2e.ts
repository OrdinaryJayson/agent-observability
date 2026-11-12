import { expect, test, type Page } from '@playwright/test'
import examples from '../../contracts/v1-http-examples.json' with { type: 'json' }
import type { Agent, BenchmarkResult, Run, Span, SpanEvent, Task } from '../src/types'

test.use({ timezoneId: 'Asia/Shanghai' })

const agentPath = '/agents/{agent_id}'
const taskPath = '/tasks/{task_id}'
const startPath = '/tasks/{task_id}/runs'
const runPath = '/runs/{run_id}'
const tracePath = '/traces/{trace_id}'
const agent = sample<{ data: Agent }>('GET', agentPath).data
const task = sample<{ data: Task }>('GET', taskPath).data
const run = sample<{ data: Run }>('GET', runPath).data
const root = sample<{ data: Span[] }>('GET', tracePath + '/spans').data[0]
const event = sample<{ data: SpanEvent[] }>('GET', tracePath + '/events').data[0]
const traceHash = `/#/trace?run=${run.run_id}`

function sample<T>(method: string, path: string): T {
  const match = examples.endpoints.find(item => item.method === method && item.path === '/api/v1' + path)
  if (!match) throw new Error(`Missing frozen example for ${method} ${path}`)
  return structuredClone(match.response) as T
}

function envelope<T>(data: T) {
  return { data, message: 'success' }
}

function paged<T>(data: T[], query: URLSearchParams) {
  const page = Number(query.get('page') ?? 1)
  const page_size = Number(query.get('page_size') ?? 20)
  const start = (page - 1) * page_size
  return { data: data.slice(start, start + page_size), meta: { page, page_size, total: data.length } }
}

function failure(code: string, message: string) {
  return { ...examples.error, error: { ...examples.error.error, code, message } }
}

function endpointPath(path: string) {
  return path
    .replace(/^\/agents\/[^/]+$/, agentPath)
    .replace(/^\/tasks\/[^/]+\/runs$/, startPath)
    .replace(/^\/tasks\/[^/]+$/, taskPath)
    .replace(/^\/runs\/[^/]+$/, runPath)
    .replace(/^\/traces\/[^/]+/, tracePath)
}

type MockRequest = { method: string; path: string; resourcePath: string; query: URLSearchParams; body: unknown }
type MockReply = { json: unknown; status?: number }

async function mockApi(page: Page, override?: (request: MockRequest) => MockReply | void | Promise<MockReply | void>) {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const headers = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    }
    const method = request.method()
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers })
    const url = new URL(request.url())
    const resourcePath = url.pathname.replace(/^\/api\/v1/, '')
    const path = endpointPath(resourcePath)
    const reply = await override?.({
      method, path, resourcePath, query: url.searchParams, body: request.postData() ? request.postDataJSON() : undefined,
    })
    if (reply) return route.fulfill({ ...reply, headers })
    const example = examples.endpoints.find(item => item.method === method && item.path === '/api/v1' + path)
    return route.fulfill(example
      ? { status: example.status, json: example.response, headers }
      : { status: 404, json: failure('RESOURCE_NOT_FOUND', '未配置的测试请求'), headers })
  })
}

test('Agent 管理可分页、筛选、查看、部分编辑和启停，并展示创建失败', async ({ page }) => {
  const writes: unknown[] = []
  let current = { ...agent, provider: 'local' }
  let createAttempts = 0
  const others = Array.from({ length: 20 }, (_, i) => ({
    ...agent,
    agent_id: `11111111-1111-4111-8111-${String(i + 2).padStart(12, '0')}`,
    name: `示例 Agent ${i + 2}`,
  }))
  await mockApi(page, ({ method, path, query, body }) => {
    if (path === '/agents' && method === 'GET') {
      const status = query.get('status')
      return { json: paged([current, ...others].filter(item => !status || item.status === status), query) }
    }
    if (path === '/agents' && method === 'POST') {
      writes.push(body)
      if (++createAttempts === 1) return { status: 422, json: failure('VALIDATION_ERROR', '该角色无效') }
      return { status: 201, json: envelope({ ...agent, name: '新 Agent', role: 'reviewer' }) }
    }
    if (path === agentPath && method === 'PATCH') {
      writes.push(body)
      current = { ...current, ...body as Partial<typeof current> }
      return { json: envelope(current) }
    }
    if (path === agentPath) return { json: envelope(current) }
  })

  await page.goto('/#/agents')
  await page.getByRole('navigation', { name: 'Agent 分页' }).getByRole('button', { name: '下一页' }).click()
  await expect(page.getByText('示例 Agent 21', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '上一页' }).click()
  await page.getByRole('button', { name: '查看 Research Agent' }).click()
  await expect(page.getByRole('heading', { name: 'Agent 详情' })).toBeVisible()
  await page.getByRole('button', { name: '编辑 Agent' }).click()
  await expect(page.getByRole('button', { name: '保存 Agent' })).toBeDisabled()
  await page.getByLabel('模型提供商').clear()
  await page.getByRole('button', { name: '保存 Agent' }).click()
  await expect(page.getByText('已保存修改。')).toBeVisible()
  await page.getByRole('button', { name: '停用 Agent' }).click()
  await expect(page.getByText('已停用 Agent。')).toBeVisible()
  await page.getByLabel('Agent 状态').selectOption('DISABLED')
  await expect(page.getByRole('row').filter({ hasText: 'Research Agent' })).toBeVisible()
  await expect(page.getByText('示例 Agent 2', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '启用 Agent' }).click()
  await expect(page.getByText('没有符合条件的 Agent。')).toBeVisible()

  await page.getByRole('button', { name: '新建 Agent' }).click()
  await page.getByLabel('Agent 名称').fill('新 Agent')
  await page.getByLabel('角色').fill('reviewer')
  await page.getByRole('button', { name: '保存 Agent' }).click()
  await expect(page.getByRole('alert')).toHaveText('该角色无效')
  await page.getByRole('button', { name: '保存 Agent' }).click()
  await expect(page.getByText('已创建 Agent。')).toBeVisible()
  expect(writes).toEqual([
    { provider: null }, { status: 'DISABLED' }, { status: 'ACTIVE' },
    { name: '新 Agent', role: 'reviewer', provider: null, model_name: null },
    { name: '新 Agent', role: 'reviewer', provider: null, model_name: null },
  ])
})

test('同一个 Task 可多次执行，绑定顺序和参数正确，并可刷新恢复 Trace', async ({ page }) => {
  const second = { ...agent, name: 'Analysis Agent', agent_id: '11111111-1111-4111-8111-111111111112' }
  const newTask = { ...task, title: '自定义任务', description: '课程演示' }
  const secondRun = {
    ...run, run_id: '33333333-3333-4333-8333-333333333334', trace_id: 'b'.repeat(32),
  }
  const config: unknown[] = []
  let poll = 0
  let taskReads = 0
  let created = false
  await mockApi(page, ({ method, path, resourcePath, query, body }) => {
    if (path === '/tasks' && method === 'POST') {
      expect(body).toEqual({ title: '自定义任务', description: '课程演示', scenario_type: 'GENERAL' })
      created = true
      return { status: 201, json: envelope(newTask) }
    }
    if (path === '/tasks' && method === 'GET') return { json: paged(created ? [newTask] : [], query) }
    if (path === taskPath) {
      taskReads++
      return { json: envelope(newTask) }
    }
    if (path === '/agents') {
      expect(query.get('status')).toBe('ACTIVE')
      return { json: paged([agent, second], query) }
    }
    if (path === startPath) {
      expect(resourcePath).toBe(`/tasks/${task.task_id}/runs`)
      config.push(body)
      poll = 0
      const accepted = sample<{ data: { run_id: string; trace_id: string } }>('POST', startPath)
      if (config.length > 1) Object.assign(accepted.data, { run_id: secondRun.run_id, trace_id: secondRun.trace_id })
      return { status: 202, json: accepted }
    }
    if (path === runPath) {
      const current = resourcePath.endsWith(secondRun.run_id) ? secondRun : run
      return { json: envelope(poll++ === 0 ? { ...current, status: 'RUNNING', ended_at: null } : current) }
    }
    if (resourcePath === `/traces/${secondRun.trace_id}`) {
      const trace = sample<{ data: object }>('GET', tracePath).data
      return { json: envelope({ ...trace, run_id: secondRun.run_id, trace_id: secondRun.trace_id }) }
    }
  })

  await page.goto('/#/tasks')
  await expect(page.getByText('暂无任务，可以先新建一个任务。')).toBeVisible()
  await page.getByRole('button', { name: '新建任务' }).click()
  await page.getByLabel('任务名称').fill('自定义任务')
  await page.getByLabel('任务描述').fill('课程演示')
  await page.getByRole('button', { name: '创建任务' }).click()
  await expect(page.getByRole('heading', { name: '任务详情' })).toBeVisible()
  await page.getByRole('link', { name: '查看该任务的运行历史' }).click()
  await expect(page.getByLabel('Task ID')).toHaveValue(task.task_id)
  await page.getByRole('link', { name: '任务管理', exact: true }).click()
  await page.getByRole('button', { name: '查看 自定义任务' }).click()
  await page.getByLabel('绑定已启用的 Agent').check()
  await page.getByLabel('Analysis Agent').check()
  await page.getByLabel('Research Agent').check()
  await page.getByLabel('最少 Span 数').fill('21')
  await page.getByRole('button', { name: '启动模拟 Run' }).click()
  await expect(page.getByRole('alert')).toHaveText('最少 Span 数不能大于最多 Span 数')
  await page.getByLabel('最多 Span 数').fill('21')
  await page.getByRole('button', { name: '启动模拟 Run' }).click()
  await expect(page.getByText('RUNNING', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Trace 调用树' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Trace 调用树' })).toBeVisible()
  await page.getByRole('link', { name: '任务管理', exact: true }).click()
  await page.getByRole('button', { name: '查看 自定义任务' }).click()
  await page.getByRole('button', { name: '启动模拟 Run' }).click()
  await expect(page.getByRole('heading', { name: 'Trace 调用树' })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`run=${secondRun.run_id}$`))
  expect(taskReads).toBe(2)
  expect(config).toEqual([
    { source_type: 'SIMULATED', simulation_config: {
      agent_ids: [second.agent_id, agent.agent_id], agent_count: 2, min_spans: 21, max_spans: 21, failure_rate: 0.1, seed: 42,
    } },
    { source_type: 'SIMULATED', simulation_config: { agent_count: 3, min_spans: 8, max_spans: 20, failure_rate: 0.1, seed: 42 } },
  ])
})

test('运行历史提交已约定的筛选字段，并能分页打开 Trace', async ({ page }) => {
  const filters: Record<string, string>[] = []
  const runs = Array.from({ length: 21 }, (_, i) => ({
    ...run, run_id: i === 20 ? run.run_id : `33333333-3333-4333-8333-${String(i).padStart(12, '0')}`,
  }))
  await mockApi(page, ({ path, query }) => {
    if (path !== '/runs') return
    filters.push(Object.fromEntries(query))
    return { json: paged(runs, query) }
  })
  await page.goto('/#/runs')
  await page.getByLabel('Task ID').fill(task.task_id)
  await page.getByLabel('运行状态').selectOption('SUCCESS')
  await page.getByLabel('运行来源').selectOption('SIMULATED')
  await page.getByLabel('开始时间').fill('2026-11-10T08:00')
  await page.getByLabel('结束时间').fill('2026-11-10T09:00')
  await page.getByRole('button', { name: '筛选运行' }).click()
  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.getByText('第 2 / 2 页 · 共 21 条')).toBeVisible()
  expect(filters.at(-1)).toEqual({
    task_id: task.task_id, status: 'SUCCESS', source_type: 'SIMULATED', page: '2', page_size: '20',
    start_time: '2026-11-10T00:00:00.000Z', end_time: '2026-11-10T01:00:00.000Z',
  })
  await page.getByRole('link', { name: '查看 Trace' }).click()
  await expect(page.getByRole('heading', { name: 'Trace 调用树' })).toBeVisible()
})

test('Trace 拒绝不完整分页，重试后加载 105 个 Span 与 101 条事件', async ({ page }) => {
  const spans = [root, ...Array.from({ length: 104 }, (_, i): Span => ({
    ...root, span_id: (i + 2).toString(16).padStart(16, '0'),
    parent_span_id: root.span_id, span_name: `检索步骤 ${i + 1}`, operation_type: 'LLM',
    start_time: '2026-11-10T00:00:00.200Z', end_time: '2026-11-10T00:00:00.450Z', duration_ms: 250,
    provider: 'mock', model_name: 'sample', input_tokens: 42, output_tokens: 8,
    ...(i === 103 ? { status: 'ERROR', error_type: 'RetryableError', error_message: '第一次调用失败' } : {}),
  }))]
  const events = Array.from({ length: 101 }, (_, i): SpanEvent => ({
    ...event, event_id: `44444444-4444-4444-8444-${String(i).padStart(12, '0')}`,
    span_id: i === 100 ? spans[104].span_id : root.span_id, event_name: `采集事件 ${i + 1}`,
  }))
  let incomplete = true
  await mockApi(page, ({ path, query }) => {
    if (path === tracePath) return { json: envelope({
      ...sample<{ data: object }>('GET', tracePath).data, span_count: 105, error_count: 1,
    }) }
    if (path === tracePath + '/spans') {
      const data = incomplete ? spans.slice(0, 100) : spans
      incomplete = false
      return { json: paged(data, query) }
    }
    if (path === tracePath + '/events') return { json: paged(events, query) }
  })
  await page.goto(traceHash)
  await expect(page.getByRole('alert')).toContainText('Span 分页结果与轨迹总数不一致')
  await expect(page.locator('.tree-row')).toHaveCount(0)
  await page.getByRole('button', { name: '查询 / 重试' }).click()
  await expect(page.getByText('105 个 Span · 1 个失败 Span · 101 条事件')).toBeVisible()
  await expect(page.getByRole('heading', { name: '运行详情' }).locator('..')).toContainText('SUCCESS')
  await expect(page.locator('.tree-row')).toHaveCount(105)
  const step = page.locator('.timeline-row').filter({ hasText: '检索步骤 104' })
  await expect(step.locator('.timeline-bar')).toHaveCSS('left', /^\d/)
  expect(await step.locator('.timeline-bar').getAttribute('style')).toContain('left: 20%; width: 25%')
  await step.click()
  await expect(page.getByRole('heading', { name: '检索步骤 104' })).toBeVisible()
  await expect(page.getByText('42 / 8', { exact: true })).toBeVisible()
  await expect(page.getByText('第一次调用失败', { exact: true })).toBeVisible()
  await expect(page.locator('.tree-row[aria-pressed=true]')).toContainText('检索步骤 104')
  await expect(page.getByText('采集事件 101', { exact: true })).toBeVisible()
  await expect(page.getByText('采集事件 1', { exact: true })).toHaveCount(0)
})

test('全局日志处理失败重试、UTC 时间和全部筛选，并可定位关联 Span 与事件', async ({ page }) => {
  const filters: Record<string, string>[] = []
  const related = sample<{ data: object[] }>('GET', '/events').data[0]
  let failed = false
  await mockApi(page, ({ path, query }) => {
    if (path !== '/events') return
    filters.push(Object.fromEntries(query))
    if (!failed) {
      failed = true
      return { status: 500, json: failure('INTERNAL_ERROR', '日志暂不可用') }
    }
    return { json: paged([related], query) }
  })
  await page.goto('/#/logs')
  await expect(page.getByRole('alert')).toHaveText('日志暂不可用')
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page.getByText('模拟完成')).toBeVisible()
  await page.getByLabel('日志等级').selectOption('INFO')
  await page.getByLabel('Task ID').fill(task.task_id)
  await page.getByLabel('Agent ID').fill(agent.agent_id)
  await page.getByLabel('Run ID').fill(run.run_id)
  await page.getByLabel('Trace ID').fill(run.trace_id)
  await page.getByLabel('错误类型').fill('SimulatedToolError')
  await page.getByLabel('开始时间').fill('2026-11-10T08:00')
  await page.getByLabel('结束时间').fill('2026-11-10T07:59')
  await page.getByRole('button', { name: '筛选日志' }).click()
  await expect(page.getByRole('alert')).toHaveText('开始时间必须早于结束时间')
  await page.getByLabel('结束时间').fill('2026-11-10T09:00')
  await page.getByRole('button', { name: '筛选日志' }).click()
  await expect.poll(() => filters.at(-1)).toEqual({
    severity: 'INFO', task_id: task.task_id, agent_id: agent.agent_id, run_id: run.run_id, trace_id: run.trace_id,
    error_type: 'SimulatedToolError', from: '2026-11-10T00:00:00.000Z', to: '2026-11-10T01:00:00.000Z',
    page: '1', page_size: '20',
  })
  await page.getByRole('button', { name: '清空筛选' }).click()
  await expect.poll(() => filters.at(-1)).toEqual({ page: '1', page_size: '20' })
  await page.getByRole('link', { name: '定位 Trace' }).click()
  await expect(page.locator('.focused-event')).toContainText(event.event_name)
  await expect(page.getByLabel('仅显示当前 Span 的事件')).toBeChecked()
  await expect(page.locator('.tree-row[aria-pressed=true]')).toContainText(root.span_name)
})

test('总览补齐 UTC 缺失日期，区分空统计和零值，并展示 Agent 与工具统计', async ({ page }) => {
  await mockApi(page, ({ path, query }) => {
    if (query.has('from')) {
      if (path === '/analytics/overview') return { json: examples.empty_overview }
      if (path.startsWith('/analytics/')) return { json: examples.empty_list }
    }
    if (path === '/analytics/trend') return { json: paged([
      { date: '2026-11-10', total_runs: 1, success_runs: 1, failed_runs: 0 },
      { date: '2026-11-12', total_runs: 1, success_runs: 0, failed_runs: 1 },
    ], query) }
  })
  await page.goto('/#/overview')
  await expect(page.locator('.metric').filter({ hasText: 'P95 耗时' })).toContainText('1,000 ms')
  await expect(page.getByLabel('2026-11-11 总运行 0，成功 0，失败 0')).toBeVisible()
  await expect(page.getByText('SimulatedToolError')).toBeVisible()
  await page.getByLabel('开始时间').fill('2026-11-13T08:00')
  await page.getByRole('button', { name: '应用时间窗口' }).click()
  await expect(page.getByText('该时间窗口暂无运行。')).toBeVisible()
  await expect(page.locator('.metric').filter({ hasText: '成功率' })).toContainText('—')
  await expect(page.locator('.metric').filter({ hasText: '输入 Token' })).toContainText('0')
  await expect(page.getByText('该时间窗口暂无异常。')).toBeVisible()
  await page.getByRole('button', { name: '清空时间' }).click()
  await expect(page.getByText('SimulatedToolError')).toBeVisible()

  await page.getByRole('link', { name: '性能分析', exact: true }).click()
  await expect(page.getByRole('row').filter({ hasText: 'Research Agent' })).toContainText('20')
  await expect(page.getByRole('row').filter({ hasText: 'mock_search' })).toContainText('10 ms')
  await page.getByLabel('开始时间').fill('2026-11-13T08:00')
  await page.getByRole('button', { name: '应用时间窗口' }).click()
  await expect(page.getByText('该时间窗口暂无已关联 Agent 的统计。')).toBeVisible()
  await expect(page.getByText('该时间窗口暂无工具调用统计。')).toBeVisible()
})

test('索引实验使用预设参数，处理禁用与超时，刷新后可查看服务端历史', async ({ page }) => {
  const fixture = sample<{ data: BenchmarkResult }>('POST', '/benchmarks/run').data
  const history: BenchmarkResult[] = [fixture]
  const inputs: unknown[] = []
  await mockApi(page, ({ path, query, body }) => {
    if (path === '/benchmarks/results') return { json: paged(history, query) }
    if (path !== '/benchmarks/run') return
    inputs.push(body)
    if (inputs.length === 1) return { status: 409, json: failure('FEATURE_NOT_AVAILABLE', '实验未启用') }
    if (inputs.length === 2) return { status: 201, json: envelope(fixture) }
    if (inputs.length === 3) return { status: 504, json: failure('BENCHMARK_TIMEOUT', '实验执行超时') }
    const result: BenchmarkResult = {
      ...fixture, ...body as Pick<BenchmarkResult, 'case_code' | 'dataset_size'>,
      result_id: '55555555-5555-4555-8555-555555555556', index_strategy: 'no_index_vs_error_partial',
      duration_ms: 0, plan: { ...fixture.plan, duration_after_ms: 0, after: { 'Execution Time': 0 } },
    }
    history.unshift(result)
    return { status: 201, json: envelope(result) }
  })
  await page.goto('/#/benchmarks')
  await expect(page.getByLabel('实验案例').locator('option')).toHaveCount(2)
  await expect(page.getByLabel('数据规模（Span 行）').locator('option')).toHaveCount(3)
  await page.getByRole('button', { name: '运行实验' }).click()
  await expect(page.getByRole('alert')).toHaveText('实验未启用')
  await page.getByRole('button', { name: '运行实验' }).click()
  await expect(page.getByRole('heading', { name: '按 Run 查询轨迹 · 复合索引' })).toBeVisible()
  await expect(page.locator('dt:has-text("加速比") + dd')).toHaveText('2×')
  await page.getByLabel('实验案例').selectOption('ERROR_PARTIAL_INDEX')
  await page.getByLabel('数据规模（Span 行）').selectOption('100000')
  await page.getByRole('button', { name: '运行实验' }).click()
  await expect(page.getByRole('alert')).toHaveText('实验执行超时')
  await page.getByRole('button', { name: '运行实验' }).click()
  await expect(page.getByRole('heading', { name: '建索引前的执行计划' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '建索引后的执行计划' })).toBeVisible()
  await expect(page.getByText('2 ms / 0 ms').first()).toBeVisible()
  await expect(page.locator('dt:has-text("加速比") + dd')).toHaveText('—')
  await page.reload()
  await page.getByRole('button', { name: '查看执行计划' }).first().click()
  await expect(page.getByRole('heading', { name: '按时间查询失败 Span · 部分索引' })).toBeVisible()
  expect(inputs).toEqual([
    { case_code: 'TRACE_QUERY_INDEX', dataset_size: 1000 },
    { case_code: 'TRACE_QUERY_INDEX', dataset_size: 1000 },
    { case_code: 'ERROR_PARTIAL_INDEX', dataset_size: 100000 },
    { case_code: 'ERROR_PARTIAL_INDEX', dataset_size: 100000 },
  ])
})

test('快速执行在查询失败后可重试，失败零 Span 正常显示且移动端不溢出', async ({ page }) => {
  let starts = 0
  let queries = 0
  await mockApi(page, ({ path, body }) => {
    if (path === startPath) {
      starts++
      expect(body).toEqual({ source_type: 'SIMULATED', simulation_config: { failure_rate: 1 } })
    }
    if (path === runPath) {
      if (++queries === 1) return { status: 500, json: failure('INTERNAL_ERROR', '查询暂时失败') }
      return { json: envelope({ ...run, status: 'FAILED', error_summary: '模拟器异常' }) }
    }
    if (path === tracePath) {
      return { json: envelope({ ...sample<{ data: object }>('GET', tracePath).data, status: 'FAILED', span_count: 0 }) }
    }
    if (path === tracePath + '/spans' || path === tracePath + '/events') return { json: examples.empty_list }
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByLabel('生成工具失败场景').check()
  await page.getByRole('button', { name: '创建并执行' }).click()
  await expect(page.getByRole('alert')).toContainText('查询暂时失败')
  await page.reload()
  await expect(page.getByLabel('恢复查询已有 Run')).toHaveValue(run.run_id)
  await page.getByRole('button', { name: '查询 / 重试' }).click()
  await expect(page.getByText('模拟器异常', { exact: true })).toBeVisible()
  await expect(page.getByText('本次运行没有可用的轨迹数据。')).toBeVisible()
  expect(starts).toBe(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
