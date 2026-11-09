import { describe, expect, it } from 'vitest'
import type { Span } from '../types'
import { flattenTree } from './tree'

const span = (id: string, parent: string | null) => ({ span_id: id, parent_span_id: parent } as Span)

describe('trace tree', () => {
  it('builds the tree from out-of-order spans', () => {
    expect(flattenTree([span('child', 'root'), span('leaf', 'child'), span('root', null)])
      .map(row => [row.span.span_id, row.depth])).toEqual([['root', 0], ['child', 1], ['leaf', 2]])
  })
  it('rejects a disconnected cycle', () => {
    expect(() => flattenTree([span('root', null), span('a', 'b'), span('b', 'a')])).toThrow()
  })
  it('rejects incomplete pagination results', () => {
    expect(() => flattenTree([span('child', 'root')])).toThrow()
  })
})
