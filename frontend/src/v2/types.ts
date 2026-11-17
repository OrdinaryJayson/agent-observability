import type { Run, Span, SpanEvent } from '../types'

export const scenarios = ['RESEARCH_PIPELINE', 'PARALLEL_RETRIEVAL', 'QUALITY_GATE'] as const
export const nodeTypes = ['START', 'END', 'LLM', 'TOOL', 'RETRIEVAL', 'MERGE', 'CONDITION'] as const
export type NodeType = typeof nodeTypes[number]
export type NodeStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'ERROR' | 'SKIPPED' | 'CANCELLED'
export type ClockMode = 'REALTIME' | 'VIRTUAL' | 'LEGACY'
export type ExecutionState = 'QUEUED' | 'RUNNING' | 'RECOVERING' | 'FINALIZING' | 'FINISHED'
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }
export type JsonObject = { [key: string]: Json }

export interface WorkflowNode {
  node_key: string
  name: string
  role_key: string | null
  type: NodeType
  config: {
    duration_ms?: number
    failure_probability?: number
    max_retries?: number
    input_tokens?: number
    output_tokens?: number
    result?: 'PASS' | 'FAIL' | 'SEEDED'
  }
}

export interface Edge { source: string; target: string; route: 'ALWAYS' | 'PASS' | 'FAIL' }
export interface Definition {
  schema_version: '2.0'
  scenario: typeof scenarios[number]
  roles: { role_key: string; name: string }[]
  nodes: WorkflowNode[]
  edges: Edge[]
}

export interface Workflow {
  workflow_id: string
  name: string
  description: string | null
  draft: Definition
  revision: number
  archived_at: string | null
  created_at: string
  updated_at: string
}
export interface Version {
  version_id: string
  workflow_id: string
  version_no: number
  definition: Definition
  definition_hash: string
  created_at: string
}
export interface Validation {
  valid: boolean
  errors: { code: string; node_key: string | null; edge_index: number | null; path: string; message: string }[]
}
export interface RunView extends Run {
  version_id: string | null
  workflow_name: string | null
  version_no: number | null
  mode: ClockMode
  execution_state: ExecutionState | null
  queued_at: string | null
  execution_started_at: string | null
  execution_ended_at: string | null
  queue_duration_ms: number | null
  execution_duration_ms: number | null
  logical_duration_ms: number | null
  last_seq: number
  cancel_requested_at: string | null
  recovery_count: number
  span_count: number
  error_count: number
  progress: number | null
}
export interface RunStart {
  version_id: string
  agent_bindings: Record<string, string>
  unbound: boolean
  seed: number
  mode: Exclude<ClockMode, 'LEGACY'>
  max_parallelism: number
  priority: number
  retry_of_run_id: string | null
  dataset_id: string | null
}
export type AcceptedRunV2 = Pick<RunView, 'run_id' | 'trace_id' | 'execution_state' | 'status' | 'version_id'>
export interface NodeState { node_key: string; state: NodeStatus; attempt_no: number; span_ids: string[] }
type FinishedFields = Pick<Span, 'span_id' | 'status' | 'end_time' | 'input_tokens' | 'output_tokens' | 'provider' | 'model_name' | 'tool_name' | 'error_type' | 'error_message'>
export interface SpanOpen extends Pick<Span, 'span_id' | 'parent_span_id' | 'agent_id' | 'operation_type' | 'span_name' | 'start_time' | 'attributes'> {
  node_key: string | null
  role_key: string | null
  attempt_no: number
}
export interface LiveSpan extends SpanOpen, Omit<FinishedFields, 'span_id' | 'status' | 'end_time'> {
  state: 'RUNNING' | 'SUCCESS' | 'ERROR'
  end_time: string | null
}
export interface Link { source_span_id: string; target_span_id: string; link_type: 'DEPENDS_ON' | 'RETRY_OF' }
export interface Snapshot {
  run: RunView
  seq: number
  nodes: NodeState[]
  spans: LiveSpan[]
  links: Link[]
  event_count: number
  projection_complete: boolean
}

interface JournalPayload {
  'run.queued': { execution_state: 'QUEUED' }
  'run.started': { lease_epoch: number }
  'span.started': SpanOpen
  'span.finished': FinishedFields
  'span.event': SpanEvent
  'link.created': Link
  'node.skipped': { node_key: string; reason: string }
  'checkpoint.saved': { checkpoint_version: number }
  'cancel.requested': JsonObject
  'run.recovering': { recovery_count: number }
  'run.finished': { status: Exclude<Run['status'], 'RUNNING'>; error_summary: string | null; projection_complete: boolean; final_seq: number }
}
export type JournalKind = keyof JournalPayload
export type JournalEvent = {
  [Kind in JournalKind]: {
    run_id: string; seq: number; producer_event_id: string; kind: Kind; payload: JournalPayload[Kind];
    occurred_at: string; recorded_at: string
  }
}[JournalKind]
export interface JournalPage {
  data: JournalEvent[]
  meta: { next_after_seq: number; has_more: boolean; snapshot_seq: number }
}

export interface AggregateStatus { snapshot_at: string | null; watermark_max_seq: number; stale: boolean; refreshing: boolean }
export interface OverviewV2 {
  total_runs: number
  running_runs: number
  queued_runs: number
  success_runs: number
  failed_runs: number
  cancelled_runs: number
  success_rate: number | null
  avg_execution_duration_ms: number | null
  p50_execution_duration_ms: number | null
  p95_execution_duration_ms: number | null
  input_tokens: number
  output_tokens: number
  total_spans: number
  dataset_counts: Record<string, number>
  recent_runs: RunView[]
  aggregate_status: AggregateStatus
}
export interface Analysis {
  supported?: boolean
  reason?: string
  algorithm_version: string
  journal_seq: number
  time_basis: ClockMode
  critical_path: { node_keys: string[]; duration_ms: number } | null
  self_times: { span_id: string; duration_ms: number | null }[]
  retry_overhead_ms: number
  scheduler_wait_ms: number
  recovery_pause_ms: number
  findings: { code: string; severity: string; node_keys: string[]; evidence: JsonObject; explanation: string }[]
  limitations: string[]
}
export interface Comparison {
  run_ids: string[]
  version_id: string
  time_basis: ClockMode
  summary_rows: { run_id: string; execution_duration_ms: number | null; input_tokens: number | null; output_tokens: number | null; status: Run['status'] }[]
  node_rows: { node_key: string; per_run: {
    run_id: string; state: NodeStatus; attempt_count: number; duration_ms: number | null;
    input_tokens: number | null; output_tokens: number | null
  }[] }[]
  deltas: JsonObject
}
export interface CursorPage<T> { data: T[]; meta: { limit: number; next_cursor: string | null; has_more: boolean } }
export interface Capabilities { protocol_version: '2.0'; features: Record<string, boolean>; limits: Record<string, number>; scenarios: Definition['scenario'][]; algorithm_version: string; experiment_protocol_version: string }

export const cases = {
  INDEX_SELECTIVITY: '索引与选择率', JSONB_GIN: 'JSONB 与 GIN', PAGINATION: '深分页',
  AGGREGATION: '聚合与物化视图', MVCC_ISOLATION: 'MVCC 与事务隔离', QUEUE_CONTENTION: '队列竞争',
} as const
export type CaseCode = keyof typeof cases
export interface Dataset {
  dataset_id: string; name: string; purpose: 'DEMO' | 'BENCHMARK' | 'LOAD'; state: 'BUILDING' | 'READY' | 'FAILED';
  seed: number; config: JsonObject; actual_counts: Record<string, number>; content_hash: string | null;
  generator_version: string; created_at: string; completed_at: string | null
}
export interface ExperimentStart {
  dataset_id: string; case_code: CaseCode; parameters: Record<string, string | number>; seed: number; warmups: 3; repetitions: 15 | 30
}
export interface Experiment {
  experiment_id: string; dataset_id: string; case_code: CaseCode;
  status: 'QUEUED' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED';
  phase: string | null; progress: number | null; cancel_requested_at: string | null;
  config: ExperimentStart; environment: JsonObject | null; created_at: string; ended_at: string | null;
  error_code: string | null; trial_count: number; sample_count: number; protocol_version: string; code_revision: string | null
}
export interface Trial {
  trial_id: string; ordinal: number; variant: string; parameters: JsonObject;
  summary: { n: number; median_ms: number | null; p95_ms: number | null; iqr_ms: number | null;
    paired_difference_ms: number | null; bootstrap_ci95_ms: [number, number] | null; failed_samples: number }
}
export interface Sample {
  repetition: number; is_warmup: boolean; measured_at: string; metrics: Record<string, number | null | JsonObject>;
  plan: JsonObject | null; correctness: { passed: boolean; checks: JsonObject; result_hash: string | null }
}
export interface SearchHit {
  run_id: string; trace_id: string; span_id: string; agent_id: string | null; task_id: string
  mode?: ClockMode; event_id?: string; event_name?: string; severity?: string; message?: string | null;
  occurred_at?: string; start_time?: string; span_name?: string; operation_type?: string; status?: string;
  error_type?: string | null; attributes: JsonObject
}
export interface Catalog {
  tables: { name: string; columns: Json[]; constraints: Json[]; indexes: Json[]; size_bytes: number }[]
  views: { name: string; definition: string }[]
}
