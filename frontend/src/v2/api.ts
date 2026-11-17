import type { Envelope } from '../types'
import type {
  AcceptedRunV2, AggregateStatus, Analysis, Capabilities, Catalog, Comparison, CursorPage, Dataset,
  Definition, Experiment, ExperimentStart, JournalPage, JsonObject, OverviewV2, RunStart, RunView,
  Sample, SearchHit, Snapshot, Trial, Validation, Version, Workflow,
} from './types'

const v1Base = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'
const base = (import.meta.env.VITE_V2_API_BASE_URL || v1Base.replace(/\/api\/v1\/?$/, '/api/v2')).replace(/\/$/, '')
export type Filters = Record<string, string | number | undefined>
const segment = encodeURIComponent

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string, readonly details?: unknown) {
    super(message)
  }
}

function url(path: string, filters: Filters = {}) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  return base + path + (params.size ? '?' + params : '')
}

export async function check(response: Response) {
  if (response.ok) return
  const body = await response.json().catch(() => null)
  throw new ApiError(body?.error?.message ?? `请求失败（HTTP ${response.status}）`,
    response.status, body?.error?.code, body?.error?.details)
}

async function request(path: string, signal?: AbortSignal, init?: RequestInit, filters?: Filters) {
  const timeout = AbortSignal.timeout(15000)
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout
  try {
    const response = await fetch(url(path, filters), { ...init, signal: combined })
    await check(response)
    return response
  } catch (error) {
    if (timeout.aborted && !signal?.aborted) throw new Error('请求超时（15 秒）')
    if (error instanceof TypeError && !signal?.aborted) throw new Error('无法连接 v2 API，请检查网络和服务地址')
    throw error
  }
}

async function get<T>(path: string, signal?: AbortSignal, filters?: Filters): Promise<T> {
  return (await request(path, signal, undefined, filters)).json()
}
function data<T>(path: string, signal?: AbortSignal, filters?: Filters) {
  return get<Envelope<T>>(path, signal, filters).then(result => result.data)
}
function page<T>(path: string, filters: Filters, cursor: string | undefined, signal?: AbortSignal) {
  return get<CursorPage<T>>(path, signal, { ...filters, limit: 50, cursor })
}
async function send<T>(path: string, method: 'POST' | 'PATCH', body: object, signal?: AbortSignal, headers?: Record<string, string>) {
  const response = await request(path, signal, {
    method, body: JSON.stringify(body), headers: { 'Content-Type': 'application/json', ...headers },
  })
  const result: Envelope<T> = await response.json()
  return result.data
}
const workflow = (id: string) => '/workflows/' + segment(id)
const run = (id: string) => '/runs/' + segment(id)
const experiment = (id: string) => '/experiments/' + segment(id)
const revisionHeader = (revision: number) => ({ 'If-Match': `"${revision}"` })
const idempotencyHeader = (key: string) => ({ 'Idempotency-Key': key })

export const v2 = {
  capabilities: (signal?: AbortSignal) => data<Capabilities>('/capabilities', signal),
  overview: (filters: Filters, signal?: AbortSignal) => data<OverviewV2>('/overview', signal, filters),
  workflows: (cursor?: string, signal?: AbortSignal) => page<Workflow>('/workflows', {}, cursor, signal),
  workflow: (id: string, signal?: AbortSignal) => data<Workflow>(workflow(id), signal),
  createWorkflow: (input: Pick<Workflow, 'name' | 'description' | 'draft'>, signal?: AbortSignal) =>
    send<Workflow>('/workflows', 'POST', input, signal),
  updateWorkflow: (id: string, revision: number, input: Partial<Pick<Workflow, 'name' | 'description' | 'draft'> & { archived: boolean }>, signal?: AbortSignal) =>
    send<Workflow>(workflow(id), 'PATCH', input, signal, revisionHeader(revision)),
  validate: (id: string, draft: Definition, signal?: AbortSignal) =>
    send<Validation>(workflow(id) + '/validate', 'POST', { draft }, signal),
  versions: (id: string, cursor?: string, signal?: AbortSignal) =>
    page<Version>(workflow(id) + '/versions', {}, cursor, signal),
  version: (id: string, signal?: AbortSignal) => data<Version>('/workflow-versions/' + segment(id), signal),
  publish: (id: string, revision: number, hash: string, signal?: AbortSignal) =>
    send<Version>(workflow(id) + '/versions', 'POST', { expected_definition_hash: hash }, signal, revisionHeader(revision)),
  runs: (filters: Filters, cursor?: string, signal?: AbortSignal) => page<RunView>('/runs', filters, cursor, signal),
  run: (id: string, signal?: AbortSignal) => data<RunView>(run(id), signal),
  start: (taskId: string, input: RunStart, key: string, signal?: AbortSignal) =>
    send<AcceptedRunV2>('/tasks/' + segment(taskId) + '/runs', 'POST', input, signal, idempotencyHeader(key)),
  cancelRun: (id: string, signal?: AbortSignal) => send<{ accepted: boolean; already_terminal: boolean; run: RunView }>(run(id) + '/cancel', 'POST', {}, signal),
  snapshot: (id: string, signal?: AbortSignal) => data<Snapshot>(run(id) + '/snapshot', signal),
  journal: (id: string, after: number, signal?: AbortSignal) =>
    get<JournalPage>(run(id) + '/journal', signal, { after_seq: after, limit: 100 }),
  stream: (id: string, after: number, signal: AbortSignal) =>
    fetch(url(run(id) + '/stream', { after_seq: after }), { headers: { Accept: 'text/event-stream' }, signal }),
  analysis: (id: string, signal?: AbortSignal) => data<Analysis>(run(id) + '/analysis', signal),
  compare: (ids: string[], signal?: AbortSignal) => send<Comparison>('/comparisons', 'POST', { run_ids: ids }, signal),
  search: (kind: 'spans' | 'events', filters: Filters, cursor?: string, signal?: AbortSignal) =>
    page<SearchHit>('/search/' + kind, filters, cursor, signal),
  series: (filters: Filters, signal?: AbortSignal) => data<JsonObject[]>('/analytics/series', signal, filters),
  aggregate: (signal?: AbortSignal) => data<AggregateStatus>('/analytics/aggregate-status', signal),
  refresh: (signal?: AbortSignal) => send<AggregateStatus>('/analytics/refresh', 'POST', {}, signal),
  agentStats: (filters: Filters, cursor?: string, signal?: AbortSignal) => page<JsonObject>('/analytics/agents', filters, cursor, signal),
  datasets: (cursor?: string, signal?: AbortSignal) => page<Dataset>('/datasets', {}, cursor, signal),
  dataset: (id: string, signal?: AbortSignal) => data<Dataset>('/datasets/' + segment(id), signal),
  registerDataset: (input: Pick<Dataset, 'name' | 'purpose' | 'seed' | 'config' | 'generator_version'>, signal?: AbortSignal) =>
    send<Dataset>('/datasets', 'POST', input, signal),
  experiments: (cursor?: string, signal?: AbortSignal) => page<Experiment>('/experiments', {}, cursor, signal),
  experiment: (id: string, signal?: AbortSignal) => data<Experiment>(experiment(id), signal),
  startExperiment: (input: ExperimentStart, key: string, signal?: AbortSignal) =>
    send<Experiment>('/experiments', 'POST', input, signal, idempotencyHeader(key)),
  cancelExperiment: (id: string, signal?: AbortSignal) =>
    send<unknown>(experiment(id) + '/cancel', 'POST', {}, signal),
  trials: (id: string, cursor?: string, signal?: AbortSignal) => page<Trial>(experiment(id) + '/trials', {}, cursor, signal),
  samples: (id: string, trial: string, cursor?: string, signal?: AbortSignal) =>
    page<Sample>(experiment(id) + '/samples', { trial_id: trial }, cursor, signal),
  export: async (id: string, format: 'json' | 'csv', signal: AbortSignal) => {
    const response = await request(experiment(id) + '/export', signal, undefined, { format })
    return response.blob()
  },
  catalog: (signal?: AbortSignal) => data<Catalog>('/database/catalog', signal),
  templates: (signal?: AbortSignal) => data<{ code: string; sql: string; parameters: unknown; index_names: string[]; description: string }[]>('/database/query-templates', signal),
  audit: (filters: Filters, cursor?: string, signal?: AbortSignal) => page<JsonObject>('/audit', filters, cursor, signal),
}
