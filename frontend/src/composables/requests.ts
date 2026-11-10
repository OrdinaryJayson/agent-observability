import { computed, onBeforeUnmount, ref, shallowRef } from 'vue'
import type { Page } from '../types'

export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '请求失败'
}

export function useRequest<T>() {
  const data = shallowRef<T | null>(null)
  const loading = ref(false)
  const error = ref('')
  let controller: AbortController | undefined

  function cancel() {
    controller?.abort()
    loading.value = false
  }

  async function load(fetchData: (signal: AbortSignal) => Promise<T>) {
    cancel()
    const signal = (controller = new AbortController()).signal
    loading.value = true
    error.value = ''
    data.value = null
    try {
      const result = await fetchData(signal)
      if (!signal.aborted) {
        data.value = result
        return result
      }
    } catch (cause) {
      if (!signal.aborted) error.value = errorMessage(cause)
    } finally {
      if (!signal.aborted) loading.value = false
    }
  }

  onBeforeUnmount(cancel)
  return { data, loading, error, load, cancel }
}

export function usePage<T>(fetchPage: (page: number, signal: AbortSignal) => Promise<Page<T>>) {
  const request = useRequest<Page<T>>()
  const page = ref(1)
  const items = computed(() => request.data.value?.data ?? [])
  const meta = computed(() => request.data.value?.meta ?? null)

  function load(next = page.value) {
    page.value = next
    return request.load(signal => fetchPage(next, signal))
  }

  return { ...request, items, meta, load }
}
