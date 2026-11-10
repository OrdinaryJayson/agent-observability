import type { Span } from '../types'

export interface TreeRow { span: Span; depth: number }

export function flattenTree(spans: Span[]): TreeRow[] {
  if (!spans.length) return []
  const ids = new Set(spans.map(s => s.span_id))
  if (ids.size !== spans.length) throw new Error('Trace 含重复节点')
  const children = new Map<string | null, Span[]>()
  for (const span of spans) {
    if (span.parent_span_id !== null && !ids.has(span.parent_span_id)) throw new Error('Trace 缺少父节点')
    const siblings = children.get(span.parent_span_id) || []
    siblings.push(span)
    children.set(span.parent_span_id, siblings)
  }
  if (children.get(null)?.length !== 1) throw new Error('Trace 根节点不唯一')
  const rows: TreeRow[] = []
  const queue = children.get(null)!.map(span => ({ span, depth: 0 }))
  const visited = new Set<string>()
  while (queue.length) {
    const row = queue.pop()!
    if (visited.has(row.span.span_id)) throw new Error('Trace 存在循环')
    visited.add(row.span.span_id)
    rows.push(row)
    queue.push(...(children.get(row.span.span_id) || []).slice().reverse().map(span => ({ span, depth: row.depth + 1 })))
  }
  if (rows.length !== spans.length) throw new Error('Trace 存在不可达节点')
  return rows
}

function timestamp(value: string) {
  const fraction = value.match(/\.(\d+)/)?.[1] ?? ''
  return Date.parse(value) + Number(`0.${fraction.slice(3)}`)
}

export function spanTimeline(spans: Span[]) {
  if (!spans.length) return { total: 0, rows: [] }
  const ranges = spans.map(span => ({
    span, start: timestamp(span.start_time), end: timestamp(span.end_time),
  }))
  const origin = Math.min(...ranges.map(range => range.start))
  const total = Math.max(...ranges.map(range => range.end)) - origin
  return {
    total,
    rows: ranges.map(({ span, start, end }) => {
      const offset = start - origin
      const duration = end - start
      return { span, offset, duration, left: total ? offset / total * 100 : 0, width: total ? duration / total * 100 : 0 }
    }),
  }
}
