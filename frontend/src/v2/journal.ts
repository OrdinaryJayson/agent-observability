import { ApiError, check, v2 } from './api'
import type { Definition, JournalEvent, LiveSpan, NodeState, RunView, Snapshot, SpanOpen } from './types'

export function openSpan(span: SpanOpen): LiveSpan {
  return {
    ...span, state: 'RUNNING', end_time: null, input_tokens: null, output_tokens: null,
    provider: null, model_name: null, tool_name: null, error_type: null, error_message: null,
  }
}

export function project(seed: Snapshot, records: JournalEvent[]): Snapshot {
  const run = { ...seed.run }
  const nodes = new Map(seed.nodes.map(node => [node.node_key, { ...node, span_ids: [...node.span_ids] }]))
  const spans = new Map(seed.spans.map(span => [span.span_id, span]))
  const links = [...seed.links]
  let event_count = seed.event_count
  let projection_complete = seed.projection_complete
  let seq = seed.seq

  function updateNode(key: string, state: NodeState['state'], span?: SpanOpen) {
    const node = nodes.get(key) ?? { node_key: key, state, attempt_no: 0, span_ids: [] }
    if (span && !node.span_ids.includes(span.span_id)) node.span_ids.push(span.span_id)
    if (!span || span.attempt_no >= node.attempt_no) {
      node.state = state
      node.attempt_no = span?.attempt_no ?? node.attempt_no
    }
    nodes.set(key, node)
  }

  for (const event of records) {
    if (event.seq <= seq) continue
    if (event.seq !== seq + 1 || event.run_id !== run.run_id) throw new Error('执行日志序号不连续')
    seq = event.seq
    switch (event.kind) {
      case 'run.queued': run.execution_state = 'QUEUED'; break
      case 'run.started': run.execution_state = 'RUNNING'; run.execution_started_at ??= event.occurred_at; break
      case 'run.recovering': run.execution_state = 'RECOVERING'; run.recovery_count = event.payload.recovery_count; break
      case 'cancel.requested': run.cancel_requested_at ??= event.occurred_at; break
      case 'span.started': {
        const span = event.payload
        spans.set(span.span_id, openSpan(span))
        if (span.node_key) updateNode(span.node_key, 'RUNNING', span)
        break
      }
      case 'span.finished': {
        const span = spans.get(event.payload.span_id)
        if (!span) throw new Error('收到未开始的 Span 终态')
        const { status, ...fields } = event.payload
        spans.set(span.span_id, { ...span, ...fields, state: status })
        if (span.node_key) updateNode(span.node_key, status, span)
        break
      }
      case 'span.event': event_count++; break
      case 'link.created': links.push(event.payload); break
      case 'node.skipped': updateNode(event.payload.node_key, 'SKIPPED'); break
      case 'run.finished':
        run.status = event.payload.status
        run.error_summary = event.payload.error_summary
        run.execution_state = 'FINISHED'
        run.execution_ended_at = event.occurred_at
        run.ended_at = event.occurred_at
        projection_complete = event.payload.projection_complete
        if (run.status === 'CANCELLED') {
          for (const node of nodes.values()) if (node.state === 'PENDING' || node.state === 'RUNNING') node.state = 'CANCELLED'
        }
        break
    }
  }
  run.last_seq = seq
  run.span_count = spans.size
  run.error_count = [...spans.values()].filter(span => span.state === 'ERROR').length
  run.progress = nodes.size ? [...nodes.values()].filter(node => node.state !== 'PENDING' && node.state !== 'RUNNING').length / nodes.size : null
  return { run, seq, nodes: [...nodes.values()], spans: [...spans.values()], links, event_count, projection_complete }
}

export function replayBase(run: RunView, definition: Definition): Snapshot {
  return {
    run: {
      ...run, status: 'RUNNING', execution_state: 'QUEUED', execution_started_at: null, execution_ended_at: null,
      execution_duration_ms: null, logical_duration_ms: null, queue_duration_ms: null, last_seq: 0,
      error_summary: null, ended_at: null, cancel_requested_at: null, recovery_count: 0, span_count: 0, error_count: 0, progress: 0,
    },
    seq: 0, spans: [], links: [], event_count: 0, projection_complete: false,
    nodes: definition.nodes.map(node => ({ node_key: node.node_key, state: 'PENDING', attempt_no: 0, span_ids: [] })),
  }
}

interface SseFrame { id?: string; type: string; data: string }

export async function readStream(response: Response, consume: (frame: SseFrame) => Promise<boolean>, signal: AbortSignal) {
  await check(response)
  if (!response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) {
    throw new Error('服务器未返回 SSE 事件流')
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffered = ''
  let frame: { id?: string; type: string; data: string[] } = { type: 'message', data: [] }
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read()
      if (done && !buffered.endsWith('\r')) return
      buffered += done ? '\n' : value
      // Accept CRLF, LF and isolated CR, including CRLF split between chunks.
      const lines = buffered.split(/\r\n|\n|\r(?!$)/)
      buffered = lines.pop()!
      for (const line of lines) {
        if (!line) {
          if (frame.data.length || frame.type !== 'message') {
            if (await consume({ ...frame, data: frame.data.join('\n') })) return
          }
          frame = { type: 'message', data: [] }
          continue
        }
        if (line.startsWith(':')) continue
        const colon = line.indexOf(':')
        const name = colon < 0 ? line : line.slice(0, colon)
        const field = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '')
        if (name === 'id') frame.id = field
        if (name === 'event') frame.type = field
        if (name === 'data') frame.data.push(field)
      }
      if (done) return
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export async function fillJournal(id: string, after: number, through: number, signal: AbortSignal, append: (events: JournalEvent[]) => void) {
  let cursor = after
  while (cursor < through) {
    const page = await v2.journal(id, cursor, signal)
    signal.throwIfAborted()
    const records = page.data.filter(event => event.seq <= through)
    if (!records.length) throw new Error('无法补齐执行日志')
    for (const event of records) {
      if (event.run_id !== id || event.seq !== cursor + 1) throw new Error('执行日志序号不连续')
      cursor = event.seq
    }
    append(records)
  }
}

function pause(duration: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    signal.throwIfAborted()
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, duration)
    function abort() { clearTimeout(timer); reject(signal.reason) }
    signal.addEventListener('abort', abort, { once: true })
  })
}

export async function watchRun(id: string, signal: AbortSignal, state: {
  snapshot: () => Snapshot
  reset: (snapshot: Snapshot) => void
  append: (event: JournalEvent) => void
  connection: (label: string) => void
}) {
  let retry = 500
  let failures = 0
  while (state.snapshot().run.status === 'RUNNING') {
    signal.throwIfAborted()
    let idleTimer: ReturnType<typeof setTimeout> | undefined
    const idle = new AbortController()
    const connection = AbortSignal.any([signal, idle.signal])
    try {
      idleTimer = setTimeout(() => idle.abort(), 35000)
      const response = await v2.stream(id, state.snapshot().seq, connection)
      state.connection('实时连接')
      // A response chunk, including heartbeat comments, resets the transport deadline.
      if (!response.ok) await check(response)
      const body = response.body?.pipeThrough(new TransformStream<Uint8Array, Uint8Array>({
        transform(chunk, controller) {
          clearTimeout(idleTimer)
          idleTimer = setTimeout(() => idle.abort(), 35000)
          controller.enqueue(chunk)
        },
      }))
      const wrapped = body ? new Response(body, { headers: response.headers }) : response
      await readStream(wrapped, async frame => {
        if (frame.type === 'stream.end') return true
        if (frame.type === 'stream.error') throw new Error('实时流暂时中断')
        const event = JSON.parse(frame.data) as JournalEvent
        if (event.run_id !== id || event.kind !== frame.type || String(event.seq) !== frame.id || !Number.isSafeInteger(event.seq)) {
          throw new Error('实时事件格式错误')
        }
        if (event.seq <= state.snapshot().seq) return false
        await fillJournal(id, state.snapshot().seq, event.seq - 1, signal, events => events.forEach(state.append))
        signal.throwIfAborted()
        state.append(event)
        retry = 500
        failures = 0
        return event.kind === 'run.finished'
      }, connection)
      signal.throwIfAborted()
      if (state.snapshot().run.status !== 'RUNNING') break
      // An end control frame has no business status. Recheck the authoritative snapshot.
      const next = await v2.snapshot(id, signal)
      signal.throwIfAborted()
      if (next.seq > state.snapshot().seq || next.run.status !== 'RUNNING') state.reset(next)
      if (next.run.status === 'RUNNING') failures++
    } catch (error) {
      signal.throwIfAborted()
      if (error instanceof ApiError && error.status === 410) {
        const next = await v2.snapshot(id, signal)
        signal.throwIfAborted()
        state.reset(next)
        retry = 500
      } else {
        if (error instanceof ApiError && [404, 422].includes(error.status)) throw error
        failures++
      }
    } finally {
      clearTimeout(idleTimer)
      idle.abort()
    }
    if (state.snapshot().run.status !== 'RUNNING') break
    if (failures >= 8) throw new Error('实时连接多次中断，请手动重新连接')
    state.connection('连接中断，正在续传')
    await pause(retry, signal)
    retry = Math.min(retry * 2, 8000)
  }
  state.connection('已结束')
}
