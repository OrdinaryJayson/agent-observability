export interface Envelope<T> { data: T; message: string }
export interface Page<T> { data: T[]; meta: { page: number; page_size: number; total: number } }
export interface AcceptedRun { run_id: string; trace_id: string; source_type: 'SIMULATED' | 'REAL'; status: 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED' }
export interface Run extends AcceptedRun { task_id: string; started_at: string; ended_at: string | null; error_summary: string | null; created_at: string }
export interface Trace { trace_id: string; run_id: string; task_id: string; status: Run['status']; source_type: Run['source_type']; span_count: number; error_count: number; started_at: string; ended_at: string | null }
export interface Span {
  span_id: string; parent_span_id: string | null; agent_id: string | null
  operation_type: 'WORKFLOW' | 'AGENT' | 'LLM' | 'TOOL' | 'RETRIEVAL' | 'OTHER'
  span_name: string; status: 'SUCCESS' | 'ERROR'; start_time: string; end_time: string
  provider: string | null; model_name: string | null; tool_name: string | null
  input_tokens: number | null; output_tokens: number | null
  error_type: string | null; error_message: string | null; attributes: Record<string, unknown>; duration_ms: number
}
export interface SpanEvent { event_id: string; span_id: string; event_name: string; severity: string; message: string | null; occurred_at: string; attributes: Record<string, unknown> }
