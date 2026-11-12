import type {
  AcceptedRun, Agent, AgentInput, AgentPatch, AgentStats, BenchmarkCase, BenchmarkResult,
  DatasetSize, Envelope, ErrorStats, EventFilters, GlobalEvent, Overview, Page, Run,
  RunFilters, SimulationConfig, Span, SpanEvent, Task, TaskInput, TimeWindow, ToolStats,
  Trace, TrendPoint,
} from '../types'

const base = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

async function request<T>(path: string, signal?: AbortSignal, init?: RequestInit, timeoutMs = 15000): Promise<T> {
  const timeout = AbortSignal.timeout(timeoutMs)
  const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout
  try {
    const response = await fetch(`${base}${path}`, { ...init, signal: requestSignal })
    const body = await response.json().catch((error: unknown) => {
      if (requestSignal.aborted) throw error
      if (response.ok) throw new Error('服务器返回了无法读取的响应')
      return null
    })
    if (!response.ok) throw new Error(body?.error?.message || `请求失败 (${response.status})`)
    return body as T
  } catch (error) {
    if (timeout.aborted && !signal?.aborted) throw new Error(`请求超时（${timeoutMs / 1000} 秒）`)
    if (error instanceof TypeError) throw new Error('无法连接到 API，请检查服务地址或网络连接')
    throw error
  }
}

function query(path: string, filters: Record<string, string | number | undefined>) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  const search = params.toString()
  return search ? `${path}?${search}` : path
}

function list<T>(
  path: string,
  page: number,
  signal?: AbortSignal,
  filters: Record<string, string | number | undefined> = {},
  pageSize = 20,
) {
  return request<Page<T>>(query(path, { ...filters, page, page_size: pageSize }), signal)
}

function send<T>(path: string, method: 'POST' | 'PATCH', body: object, signal?: AbortSignal, timeout?: number) {
  return request<Envelope<T>>(path, signal, {
    method, body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' },
  }, timeout)
}

// Load the complete collection before deriving parent-child relationships.
export async function allPages<T>(fetchPage: (page: number) => Promise<Page<T>>): Promise<T[]> {
  const items: T[] = []
  for (let page = 1; ; page++) {
    const result = await fetchPage(page)
    items.push(...result.data)
    if (items.length >= result.meta.total) return items
    if (!result.data.length) throw new Error('分页结果不完整，请重试')
  }
}

export const api = {
  agents: (page: number, status: Agent['status'] | '', signal?: AbortSignal) =>
    list<Agent>('/agents', page, signal, { status }),
  agent: (id: string, signal?: AbortSignal) => request<Envelope<Agent>>(`/agents/${encodeURIComponent(id)}`, signal),
  createAgent: (input: AgentInput, signal?: AbortSignal) => send<Agent>('/agents', 'POST', input, signal),
  updateAgent: (id: string, input: AgentPatch, signal?: AbortSignal) =>
    send<Agent>(`/agents/${encodeURIComponent(id)}`, 'PATCH', input, signal),
  tasks: (page: number, signal?: AbortSignal) => list<Task>('/tasks', page, signal),
  task: (id: string, signal?: AbortSignal) => request<Envelope<Task>>(`/tasks/${encodeURIComponent(id)}`, signal),
  createTask: (input: TaskInput, signal?: AbortSignal) => send<Task>('/tasks', 'POST', input, signal),
  startRun: (taskId: string, config: SimulationConfig, signal?: AbortSignal) =>
    send<AcceptedRun>(`/tasks/${encodeURIComponent(taskId)}/runs`, 'POST', {
      source_type: 'SIMULATED', simulation_config: config,
    }, signal),
  runs: (page: number, filters: RunFilters, signal?: AbortSignal) =>
    list<Run>('/runs', page, signal, { ...filters }),
  run: (id: string, signal?: AbortSignal) => request<Envelope<Run>>(`/runs/${encodeURIComponent(id)}`, signal),
  trace: (id: string, signal?: AbortSignal) => request<Envelope<Trace>>(`/traces/${encodeURIComponent(id)}`, signal),
  spans: (id: string, signal?: AbortSignal) => allPages<Span>(
    page => list(`/traces/${encodeURIComponent(id)}/spans`, page, signal, {}, 100),
  ),
  events: (id: string, signal?: AbortSignal) => allPages<SpanEvent>(
    page => list(`/traces/${encodeURIComponent(id)}/events`, page, signal, {}, 100),
  ),
  logs: (page: number, filters: EventFilters, signal?: AbortSignal) =>
    list<GlobalEvent>('/events', page, signal, { ...filters }),
  overview: (window: TimeWindow, signal?: AbortSignal) =>
    request<Envelope<Overview>>(query('/analytics/overview', { ...window }), signal),
  trend: (window: TimeWindow, signal?: AbortSignal) => allPages<TrendPoint>(
    page => list('/analytics/trend', page, signal, { ...window }, 100),
  ),
  errors: (page: number, window: TimeWindow, signal?: AbortSignal) =>
    list<ErrorStats>('/analytics/errors', page, signal, { ...window }),
  agentStats: (page: number, window: TimeWindow, signal?: AbortSignal) =>
    list<AgentStats>('/analytics/agents', page, signal, { ...window }),
  toolStats: (page: number, window: TimeWindow, signal?: AbortSignal) =>
    list<ToolStats>('/analytics/tools', page, signal, { ...window }),
  benchmarks: (page: number, signal?: AbortSignal) => list<BenchmarkResult>('/benchmarks/results', page, signal),
  runBenchmark: (caseCode: BenchmarkCase, datasetSize: DatasetSize, signal?: AbortSignal) =>
    send<BenchmarkResult>('/benchmarks/run', 'POST', { case_code: caseCode, dataset_size: datasetSize }, signal, 150000),
}
