import type { AcceptedRun, Envelope, Page, Run, Span, SpanEvent, Trace } from '../types'

const base = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    signal: AbortSignal.any([...(signal ? [signal] : []), AbortSignal.timeout(15000)]),
    headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
  })
  const body = await response.json()
  if (!response.ok) throw new Error(body.error?.message || `请求失败 (${response.status})`)
  return body as T
}

// Fetch all pages before constructing the tree; don't truncate at 100 spans.
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
  createTask: (title: string, signal?: AbortSignal) => request<Envelope<{ task_id: string }>>('/tasks', {
    method: 'POST', body: JSON.stringify({ title }),
  }, signal),
  startRun: (taskId: string, fail: boolean, signal?: AbortSignal) => request<Envelope<AcceptedRun>>(`/tasks/${taskId}/runs`, {
    method: 'POST', body: JSON.stringify({ source_type: 'SIMULATED', simulation_config: { failure_rate: fail ? 1 : 0 } }),
  }, signal),
  run: (id: string, signal?: AbortSignal) => request<Envelope<Run>>(`/runs/${id}`, undefined, signal),
  trace: (id: string, signal?: AbortSignal) => request<Envelope<Trace>>(`/traces/${id}`, undefined, signal),
  spans: (id: string, signal?: AbortSignal) => allPages<Span>(page => request(`/traces/${id}/spans?page=${page}&page_size=100`, undefined, signal)),
  events: (id: string, signal?: AbortSignal) => allPages<SpanEvent>(page => request(`/traces/${id}/events?page=${page}&page_size=100`, undefined, signal)),
}
