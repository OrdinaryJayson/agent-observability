import { expect, it, vi } from 'vitest'
import { allPages, api } from './client'

it('loads all 105 spans across pages', async () => {
  const result = await allPages(async page => ({
    data: Array.from({ length: page === 1 ? 100 : 5 }, (_, i) => (page - 1) * 100 + i),
    meta: { page, page_size: 100, total: 105 },
  }))
  expect(result).toHaveLength(105)
  expect(result[104]).toBe(104)
})

it('rejects a broken page instead of silently truncating the tree', async () => {
  await expect(allPages(async () => ({ data: [], meta: { page: 1, page_size: 100, total: 5 } }))).rejects.toThrow()
})

it('uses the long timeout only for benchmark execution', async () => {
  const timeout = vi.spyOn(AbortSignal, 'timeout')
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}')))
  try {
    await api.runBenchmark('ERROR_PARTIAL_INDEX', 100000)
    await api.benchmarks(1)
    expect(timeout.mock.calls).toEqual([[150000], [15000]])
  } finally {
    timeout.mockRestore()
    vi.unstubAllGlobals()
  }
})
