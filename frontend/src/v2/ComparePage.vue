<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import LoadState from '../components/LoadState.vue'
import { useRequest } from '../composables/requests'
import { count, ms } from '../utils/format'
import { v2 } from './api'
import CursorNav from './CursorNav.vue'
import JsonDetails from './JsonDetails.vue'
import { traceLink, useCursor } from './state'
import type { Comparison, RunView } from './types'

const request = useRequest<Comparison>()
const list = useCursor((cursor, signal) => v2.runs({}, cursor, signal))
const chosen = ref<RunView[]>([])
const top = computed(() => chosen.value[0])
const hint = ref('')
function toggle(run: RunView) {
  hint.value = ''
  if (chosen.value.some(row => row.run_id === run.run_id)) {
    chosen.value = chosen.value.filter(row => row.run_id !== run.run_id)
    return
  }
  if (!run.version_id || run.mode === 'LEGACY' || run.status === 'RUNNING') {
    hint.value = '请选择具有工作流版本的终态运行。'
  } else if (top.value && (top.value.version_id !== run.version_id || top.value.mode !== run.mode)) {
    hint.value = '比较需要同一工作流版本和同一时钟模式。'
  } else if (chosen.value.length < 5) chosen.value.push(run)
  else hint.value = '一次最多比较 5 个 Run。'
}
function compare() {
  if (chosen.value.length >= 2) void request.load(signal => v2.compare(chosen.value.map(run => run.run_id), signal))
}
function change(run: RunView, event: Event) {
  toggle(run)
  const checkbox = event.target as HTMLInputElement
  checkbox.checked = chosen.value.some(item => item.run_id === run.run_id)
}
onMounted(() => void list.load())
</script>

<template>
  <header class="page-heading"><h1>运行对比</h1><p>选择同版本、同时钟模式的 2–5 次终态运行。</p></header>
  <section class="card"><h2>选择运行</h2>
    <LoadState :loading="list.loading.value" :error="list.error.value" :empty="!list.items.value.length" @retry="list.reset()">
      <div class="table-wrap"><table><thead><tr><th>选择</th><th>运行</th><th>模式</th><th>状态</th></tr></thead><tbody>
        <tr v-for="run in list.items.value" :key="run.run_id">
          <td><input type="checkbox" :aria-label="'选择 ' + run.run_id" :checked="chosen.some(item => item.run_id === run.run_id)" @change="change(run, $event)" /></td>
          <td><a :href="traceLink(run.run_id)">{{ run.workflow_name ?? run.run_id }}</a> · 版本 {{ run.version_no ?? '—' }}</td><td>{{ run.mode }}</td><td>{{ run.status }}</td>
        </tr>
      </tbody></table></div>
    </LoadState>
    <CursorNav :back="!!list.trail.value.length" :forward="!!list.nextCursor.value" :loading="list.loading.value" @previous="list.previous" @next="list.next" />
    <div class="actions v2-toolbar"><button :disabled="chosen.length < 2 || request.loading.value" @click="compare">比较 {{ chosen.length }} 个 Run</button>
      <button v-if="chosen.length" class="secondary" @click="chosen = []">清空选择</button></div>
    <p v-if="hint" role="alert" class="error">{{ hint }}</p>
  </section>
  <LoadState :loading="request.loading.value" :error="request.error.value" @retry="compare">
    <section v-if="request.data.value" class="card"><h2>对比结果 · {{ request.data.value.time_basis }}</h2>
      <p>节点按 node_key 对齐。跳过的分支与缺失值显示为「—」。</p>
      <div class="table-wrap"><table><thead><tr><th>Run</th><th>状态</th><th>执行耗时</th><th>Token 输入 / 输出</th></tr></thead><tbody>
        <tr v-for="row in request.data.value.summary_rows" :key="row.run_id"><td><a :href="traceLink(row.run_id)">{{ row.run_id }}</a></td><td>{{ row.status }}</td><td>{{ ms(row.execution_duration_ms) }}</td><td>{{ count(row.input_tokens) }} / {{ count(row.output_tokens) }}</td></tr>
      </tbody></table></div>
      <div class="table-wrap v2-scroll"><table><thead><tr><th>节点</th><th v-for="id in request.data.value.run_ids" :key="id">{{ id.slice(0, 8) }}…</th></tr></thead><tbody>
        <tr v-for="node in request.data.value.node_rows" :key="node.node_key"><th>{{ node.node_key }}</th>
          <td v-for="id in request.data.value.run_ids" :key="id">
            <template v-for="item in node.per_run.filter(item => item.run_id === id)" :key="item.run_id">
              {{ item.state }} · {{ ms(item.duration_ms) }}<small>尝试 {{ item.attempt_count }} 次 · Token {{ count(item.input_tokens) }} / {{ count(item.output_tokens) }}</small>
            </template>
            <span v-if="!node.per_run.some(item => item.run_id === id)">—</span>
          </td>
        </tr>
      </tbody></table></div>
      <JsonDetails label="运行差值" :value="request.data.value.deltas" />
    </section>
  </LoadState>
</template>
