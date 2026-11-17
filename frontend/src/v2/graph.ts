import type { Definition, Edge, WorkflowNode } from './types'

export interface GraphNode { id: string; label: string; caption?: string; status?: string }
export interface GraphEdge { source: string; target: string; label?: string }
export const nodeWidth = 158
export const nodeHeight = 58

export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[]) {
  const incoming = new Map(nodes.map(node => [node.id, 0]))
  const outgoing = new Map<string, string[]>()
  const ranks = new Map<string, number>()
  for (const edge of edges) {
    const degree = incoming.get(edge.target)
    if (degree === undefined || !incoming.has(edge.source)) continue
    incoming.set(edge.target, degree + 1)
    const children = outgoing.get(edge.source) ?? []
    children.push(edge.target)
    outgoing.set(edge.source, children)
  }
  const queue = nodes.filter(node => incoming.get(node.id) === 0).map(node => node.id)
  for (let i = 0; i < queue.length; i++) {
    const id = queue[i]
    for (const child of outgoing.get(id) ?? []) {
      ranks.set(child, Math.max(ranks.get(child) ?? 0, (ranks.get(id) ?? 0) + 1))
      const degree = incoming.get(child)! - 1
      incoming.set(child, degree)
      if (degree === 0) queue.push(child)
    }
  }
  // Keep cyclic drafts editable and visible. Server validation reports the cycle.
  const cycleRank = Math.max(0, ...ranks.values()) + 1
  const lanes = new Map<number, number>()
  const positions = nodes.map(node => {
    const column = incoming.get(node.id) ? cycleRank : ranks.get(node.id) ?? 0
    const lane = lanes.get(column) ?? 0
    lanes.set(column, lane + 1)
    return { ...node, x: 24 + column * 216, y: 22 + lane * 86 }
  })
  return {
    positions, edges,
    width: Math.max(206, ...positions.map(node => node.x + nodeWidth + 24)),
    height: Math.max(112, ...positions.map(node => node.y + nodeHeight + 22)),
  }
}

export function nodeConfig(type: WorkflowNode['type']): WorkflowNode['config'] {
  if (type === 'CONDITION') return { result: 'SEEDED' }
  if (type === 'LLM' || type === 'TOOL' || type === 'RETRIEVAL') {
    return { duration_ms: 300, failure_probability: 0, max_retries: 0 }
  }
  return {}
}

export function initialDefinition(scenario: Definition['scenario']): Definition {
  const node = (node_key: string, type: WorkflowNode['type'], name: string, role_key: string | null = null): WorkflowNode =>
    ({ node_key, type, name, role_key, config: nodeConfig(type) })
  const edge = (source: string, target: string, route: Edge['route'] = 'ALWAYS'): Edge => ({ source, target, route })
  const begin = node('start', 'START', '开始')
  const end = node('end', 'END', '结束')
  const research = node('research', 'RETRIEVAL', '资料检索', 'researcher')
  const merge = node('merge', 'MERGE', '汇合')
  const report = node('report', 'LLM', '生成报告', 'researcher')
  const roles = [{ role_key: 'researcher', name: '研究角色' }]
  if (scenario === 'PARALLEL_RETRIEVAL') {
    return {
      schema_version: '2.0', scenario, roles,
      nodes: [begin, research, node('research_b', 'RETRIEVAL', '并行检索', 'researcher'), merge, end],
      edges: [edge('start', 'research'), edge('start', 'research_b'), edge('research', 'merge'), edge('research_b', 'merge'), edge('merge', 'end')],
    }
  }
  if (scenario === 'QUALITY_GATE') {
    return {
      schema_version: '2.0', scenario, roles,
      nodes: [begin, node('gate', 'CONDITION', '质量检查'), report, node('recheck', 'TOOL', '复核', 'researcher'), merge, end],
      edges: [edge('start', 'gate'), edge('gate', 'report', 'PASS'), edge('gate', 'recheck', 'FAIL'),
        edge('report', 'merge'), edge('recheck', 'merge'), edge('merge', 'end')],
    }
  }
  return {
    schema_version: '2.0', scenario, roles, nodes: [begin, research, report, end],
    edges: [edge('start', 'research'), edge('research', 'report'), edge('report', 'end')],
  }
}

export function canonical(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']'
  if (value !== null && typeof value === 'object') {
    const record = value as Record<string, unknown>
    return '{' + Object.keys(record).sort().map(key => JSON.stringify(key) + ':' + canonical(record[key])).join(',') + '}'
  }
  if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('定义中含非有限数值')
  if (value === undefined) throw new Error('定义中存在未填写的必填字段')
  return JSON.stringify(value)
}

export async function definitionHash(definition: Definition) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(definition)))
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('')
}
