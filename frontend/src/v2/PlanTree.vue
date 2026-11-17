<script setup lang="ts">
import { computed } from 'vue'
import type { Json, JsonObject } from './types'

const props = defineProps<{ plan: JsonObject }>()
const rows = computed(() => {
  const root = props.plan.Plan
  const pending: { node: Json; depth: number }[] = root && !Array.isArray(root) ? [{ node: root, depth: 0 }] : []
  const result: { kind: string; detail: string; depth: number }[] = []
  while (pending.length) {
    const { node, depth } = pending.pop()!
    if (!node || typeof node !== 'object' || Array.isArray(node)) continue
    result.push({
      kind: String(node['Node Type'] ?? '未知节点'),
      detail: [node['Relation Name'], node['Index Name'], node['Actual Rows'] !== undefined ? '行数 ' + node['Actual Rows'] : null,
        node['Actual Loops'] !== undefined ? '循环 ' + node['Actual Loops'] : null].filter(value => value != null).join(' · '),
      depth,
    })
    if (Array.isArray(node.Plans)) pending.push(...[...node.Plans].reverse().map(child => ({ node: child, depth: depth + 1 })))
  }
  return result
})
</script>

<template>
  <ul v-if="rows.length" class="v2-plan">
    <li v-for="(row, index) in rows" :key="index" :style="{ paddingInlineStart: Math.min(12, row.depth) * 12 + 'px' }">
      <strong>{{ row.kind }}</strong><small>{{ row.detail }}</small>
    </li>
  </ul>
  <p v-else>该样本没有查询计划树。</p>
</template>
