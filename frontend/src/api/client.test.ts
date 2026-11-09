import { expect, it } from 'vitest'
import { allPages } from './client'

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
