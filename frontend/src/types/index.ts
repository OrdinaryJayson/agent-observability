export interface Envelope<T> {
  data: T
  message: string
}

export interface Page<T> {
  data: T[]
  meta: { page: number; page_size: number; total: number }
}

export const agentStatuses = ['ACTIVE', 'DISABLED'] as const
export const runStatuses = ['RUNNING', 'SUCCESS', 'FAILED', 'CANCELLED'] as const
export const runSources = ['SIMULATED', 'REAL'] as const
export const severities = ['TRACE', 'DEBUG', 'INFO', 'WARN', 'ERROR'] as const

export interface AgentInput {
  name: string
  role: string
  provider: string | null
  model_name: string | null
}

export interface Agent extends AgentInput {
  agent_id: string
  status: typeof agentStatuses[number]
  created_at: string
}

export type AgentPatch = Partial<AgentInput & Pick<Agent, 'status'>>

export interface TaskInput {
  title: string
  description?: string | null
  scenario_type?: string
}

export interface Task {
  task_id: string
  title: string
  description: string | null
  scenario_type: string
  created_at: string
}

export interface SimulationConfig {
  agent_count?: number
  agent_ids?: string[]
  min_spans?: number
  max_spans?: number
  failure_rate?: number
  seed?: number
}

export interface AcceptedRun {
  run_id: string
  trace_id: string
  source_type: typeof runSources[number]
  status: typeof runStatuses[number]
}

export interface Run extends AcceptedRun {
  task_id: string
  started_at: string
  ended_at: string | null
  error_summary: string | null
  created_at: string
}

export interface Trace {
  trace_id: string
  run_id: string
  task_id: string
  status: Run['status']
  source_type: Run['source_type']
  span_count: number
  error_count: number
  started_at: string
  ended_at: string | null
}

export interface Span {
  span_id: string
  parent_span_id: string | null
  agent_id: string | null
  operation_type: 'WORKFLOW' | 'AGENT' | 'LLM' | 'TOOL' | 'RETRIEVAL' | 'OTHER'
  span_name: string
  status: 'SUCCESS' | 'ERROR'
  start_time: string
  end_time: string
  provider: string | null
  model_name: string | null
  tool_name: string | null
  input_tokens: number | null
  output_tokens: number | null
  error_type: string | null
  error_message: string | null
  attributes: Record<string, unknown>
  duration_ms: number
}

export interface SpanEvent {
  event_id: string
  span_id: string
  event_name: string
  severity: typeof severities[number]
  message: string | null
  occurred_at: string
  attributes: Record<string, unknown>
}

export interface GlobalEvent extends SpanEvent {
  run_id: string
  trace_id: string
  task_id: string
  agent_id: string | null
}

export interface TimeWindow {
  from?: string
  to?: string
}

export interface RunFilters {
  task_id?: string
  status?: Run['status'] | ''
  source_type?: Run['source_type'] | ''
  start_time?: string
  end_time?: string
}

export interface EventFilters extends TimeWindow {
  severity?: SpanEvent['severity'] | ''
  task_id?: string
  agent_id?: string
  run_id?: string
  trace_id?: string
  error_type?: string
}

export interface Overview {
  total_runs: number
  success_runs: number
  failed_runs: number
  success_rate: number | null
  avg_duration_ms: number | null
  p50_duration_ms: number | null
  p95_duration_ms: number | null
  total_input_tokens: number
  total_output_tokens: number
  total_spans: number
}

interface OperationStats {
  span_count: number
  error_count: number
  avg_duration_ms: number
}

export interface AgentStats extends OperationStats {
  agent_id: string
  name: string
  total_input_tokens: number
  total_output_tokens: number
}

export interface ToolStats extends OperationStats {
  tool_name: string | null
  total_duration_ms: number
}

export interface ErrorStats {
  error_type: string | null
  count: number
}

export interface TrendPoint {
  date: string
  total_runs: number
  success_runs: number
  failed_runs: number
}

export const benchmarkCases = {
  TRACE_QUERY_INDEX: '按 Run 查询轨迹 · 复合索引',
  ERROR_PARTIAL_INDEX: '按时间查询失败 Span · 部分索引',
} as const

export type BenchmarkCase = keyof typeof benchmarkCases
export type DatasetSize = 1000 | 10000 | 100000

export interface BenchmarkResult {
  result_id: string
  case_code: BenchmarkCase
  dataset_size: DatasetSize
  index_strategy: string
  duration_ms: number
  plan: {
    before: Record<string, unknown>
    after: Record<string, unknown>
    duration_before_ms: number
    duration_after_ms: number
    repeats: number
  }
  created_at: string
}
