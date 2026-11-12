export function traceHref(runId: string, spanId?: string, eventId?: string) {
  const params = new URLSearchParams({ run: runId })
  if (spanId) params.set('span', spanId)
  if (eventId) params.set('event', eventId)
  return `#/trace?${params}`
}
