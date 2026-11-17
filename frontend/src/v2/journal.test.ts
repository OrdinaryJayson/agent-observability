import { expect, it } from 'vitest'
import { project, readStream, replayBase } from './journal'
import type { Definition, JournalEvent, RunView } from './types'

it('decodes split multibyte text, split CRLF, multiline data and a final CR-only delimiter', async () => {
  const raw = new TextEncoder().encode(': heartbeat\r\nid: 1\r\nevent: span.event\r\ndata: 执行\r\ndata: 日志\r\n\r\nevent: stream.end\r\r')
  const stream = new ReadableStream({
    start(controller) {
      for (const byte of raw) controller.enqueue(Uint8Array.of(byte))
      controller.close()
    },
  })
  const received: unknown[] = []
  await readStream(new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } }), async frame => {
    received.push(frame)
    return false
  }, new AbortController().signal)
  expect(received).toEqual([
    { id: '1', type: 'span.event', data: '执行\n日志' },
    { type: 'stream.end', data: '' },
  ])
})

it('preserves earlier attempts, rejects a gap and marks unstarted nodes on cancellation', () => {
  const run = { run_id: 'run' } as RunView
  const definition = { nodes: [{ node_key: 'a' }, { node_key: 'b' }] } as Definition
  const base = replayBase(run, definition)
  const common = { run_id: 'run', occurred_at: '2026-11-16T00:00:00Z', recorded_at: '2026-11-16T00:00:00Z' }
  const records = [
    { ...common, seq: 1, kind: 'span.started', payload: { node_key: 'a', span_id: 'first', attempt_no: 1 } },
    { ...common, seq: 2, kind: 'span.finished', payload: { span_id: 'first', status: 'ERROR' } },
    { ...common, seq: 3, kind: 'span.started', payload: { node_key: 'a', span_id: 'second', attempt_no: 2 } },
    { ...common, seq: 4, kind: 'span.finished', payload: { span_id: 'second', status: 'SUCCESS' } },
    { ...common, seq: 5, kind: 'run.finished', payload: { status: 'CANCELLED', projection_complete: true, final_seq: 5 } },
  ] as JournalEvent[]
  const final = project(base, [...records.slice(0, 2), records[1], ...records.slice(2)])
  expect(final.run.status).toBe('CANCELLED')
  expect(final.spans.map(span => span.state)).toEqual(['ERROR', 'SUCCESS'])
  expect(final.nodes.map(node => [node.state, node.attempt_no])).toEqual([['SUCCESS', 2], ['CANCELLED', 0]])
  expect(base.spans).toEqual([])
  expect(() => project(base, [records[1]])).toThrow('执行日志序号不连续')
})
