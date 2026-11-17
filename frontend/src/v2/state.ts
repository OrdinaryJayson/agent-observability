import { computed, ref } from 'vue'
import { useRequest } from '../composables/requests'
import { ApiError } from './api'
import type { CursorPage } from './types'

export function useCursor<T>(get: (cursor: string | undefined, signal: AbortSignal) => Promise<CursorPage<T>>) {
  const request = useRequest<CursorPage<T>>()
  const trail = ref<string[]>([])
  const items = computed(() => request.data.value?.data ?? [])
  const nextCursor = computed(() => request.data.value?.meta.next_cursor)

  function load() { return request.load(signal => get(trail.value.at(-1), signal)) }
  function reset() { trail.value = []; return load() }
  function next() {
    if (!nextCursor.value || !request.data.value?.meta.has_more) return
    trail.value.push(nextCursor.value)
    return load()
  }
  function previous() {
    if (!trail.value.length) return
    trail.value.pop()
    return load()
  }
  return { ...request, items, load, reset, next, previous, trail, nextCursor }
}

// Keep the same key and payload when only the response might have been lost.
export function useSubmission<T>(scope: string) {
  const storageKey = 'ao-v2-pending:' + scope
  function pending() {
    try {
      const value = sessionStorage.getItem(storageKey)
      return value ? JSON.parse(value) as { key: string; payload: T } : null
    } catch { return null }
  }
  const attempt = ref(pending())
  function get(payload: T) {
    if (attempt.value) return attempt.value
    const item = { key: crypto.randomUUID(), payload }
    attempt.value = item
    sessionStorage.setItem(storageKey, JSON.stringify(item))
    return item
  }
  function clear() {
    attempt.value = null
    sessionStorage.removeItem(storageKey)
  }
  function reject(error: unknown) {
    if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 409) clear()
  }
  return { attempt, get, clear, reject }
}

export function link(page: string, params: Record<string, string | undefined> = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value)
  return '#/' + page + (query.size ? '?' + query : '')
}
export const traceLink = (id: string, span?: string, event?: string) => link('analysis', { run: id, span, event })

export function localTime(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isFinite(+date) ? new Date(+date - date.getTimezoneOffset() * 60000).toISOString().slice(0, 23) : ''
}
