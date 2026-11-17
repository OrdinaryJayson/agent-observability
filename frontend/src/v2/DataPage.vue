<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import LoadState from '../components/LoadState.vue'
import TimeFilter from '../components/TimeFilter.vue'
import { errorMessage, useRequest } from '../composables/requests'
import type { TimeWindow } from '../types'
import { count, time } from '../utils/format'
import { v2 } from './api'
import CursorNav from './CursorNav.vue'
import JsonDetails from './JsonDetails.vue'
import GraphView from './GraphView.vue'
import { link, useCursor } from './state'
import type { Catalog, Dataset, JsonObject } from './types'

const props = defineProps<{ datasetId?: string }>()
const datasets = useCursor(v2.datasets)
const dataset = useRequest<Dataset>()
const register = useRequest<Dataset>()
const catalog = useRequest<Catalog>()
const templates = useRequest<Awaited<ReturnType<typeof v2.templates>>>()
const aggregate = useRequest<Awaited<ReturnType<typeof v2.aggregate>>>()
const refresh = useRequest<Awaited<ReturnType<typeof v2.refresh>>>()
const scope = reactive({ action: '', resource_type: '', resource_id: '' })
const auditFilter = ref({})
const audit = useCursor((cursor, signal) => v2.audit(auditFilter.value, cursor, signal))
const form = reactive({ name: '', purpose: 'DEMO' as Dataset['purpose'], seed: 42, generator_version: '', config: '{}' })
const validation = ref('')
const panel = ref<'datasets' | 'catalog' | 'audit'>('datasets')
const tableName = ref('')
const relations = [
  { source: 'workflows', target: 'workflow_versions' },
  { source: 'workflow_versions', target: 'run_executions' },
  { source: 'runs', target: 'run_executions' },
  { source: 'runs', target: 'spans' },
  { source: 'runs', target: 'run_summaries' },
  { source: 'run_executions', target: 'run_journal' },
  { source: 'spans', target: 'span_links' },
  { source: 'dataset_manifests', target: 'experiment_runs' },
  { source: 'experiment_runs', target: 'experiment_trials' },
  { source: 'experiment_trials', target: 'experiment_samples' },
]
const designNodes = [...new Set(relations.flatMap(relation => [relation.source, relation.target]))]
  .map(id => ({ id, label: id }))

function selectTable(name: string) {
  tableName.value = name
  document.getElementById('v2-table-' + name)?.scrollIntoView({ block: 'nearest' })
}

function openPanel(next: typeof panel.value) {
  panel.value = next
  if (next === 'catalog') {
    if (!catalog.data.value && !catalog.loading.value) void catalog.load(v2.catalog)
    if (!templates.data.value && !templates.loading.value) void templates.load(v2.templates)
  }
  if (next === 'audit' && !audit.data.value && !audit.loading.value) void audit.load()
}
async function create() {
  if (register.loading.value) return
  validation.value = ''
  try {
    const config: unknown = JSON.parse(form.config)
    if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error('数据集配置必须为 JSON 对象')
    const { name, purpose, seed, generator_version } = form
    const result = await register.load(signal => v2.registerDataset({
      name: name.trim(), purpose, seed, generator_version: generator_version.trim(), config: config as JsonObject,
    }, signal))
    if (result) location.hash = link('data', { dataset: result.dataset_id })
  } catch (cause) { validation.value = errorMessage(cause) }
}
function filterAudit(window: TimeWindow) {
  auditFilter.value = { ...scope, ...window }
  void audit.reset()
}
async function refreshAggregate() {
  if (refresh.loading.value) return
  const result = await refresh.load(v2.refresh)
  if (result) aggregate.data.value = result
}
onMounted(() => {
  void datasets.load()
  void aggregate.load(v2.aggregate)
  if (props.datasetId) void dataset.load(signal => v2.dataset(props.datasetId!, signal))
})
</script>

<template>
  <header class="page-heading"><h1>数据与设计</h1><p>查看数据集、聚合水位、数据库目录与操作审计。</p></header>
  <div class="actions v2-tabs">
    <button class="secondary" :aria-pressed="panel === 'datasets'" @click="openPanel('datasets')">数据集</button>
    <button class="secondary" :aria-pressed="panel === 'catalog'" @click="openPanel('catalog')">数据库结构</button>
    <button class="secondary" :aria-pressed="panel === 'audit'" @click="openPanel('audit')">操作审计</button>
  </div>
  <section v-if="panel === 'datasets'" class="card">
    <h2>数据集登记</h2>
    <form class="form-grid" @submit.prevent="create">
      <label>名称 <input v-model.trim="form.name" required /></label>
      <label>用途 <select v-model="form.purpose"><option>DEMO</option><option>BENCHMARK</option><option>LOAD</option></select></label>
      <label>种子 <input v-model.number="form.seed" type="number" min="-2147483648" max="2147483647" required /></label>
      <label>生成器版本 <input v-model.trim="form.generator_version" required /></label>
      <label class="wide">配置（JSON） <textarea v-model="form.config" rows="2" /></label>
      <button :disabled="register.loading.value || !form.name.trim() || !form.generator_version.trim()">登记数据集</button>
    </form>
    <p v-if="validation || register.error.value" class="error" role="alert">{{ validation || register.error.value }}</p>
    <p class="muted">登记后由数据生成工具导入和核对实际数据，状态更新为 READY 后可用于运行。</p>
    <h2>数据集清单</h2>
    <LoadState :loading="datasets.loading.value" :error="datasets.error.value" :empty="!datasets.items.value.length" @retry="datasets.reset()">
      <div class="table-wrap v2-scroll"><table><thead><tr><th>名称</th><th>用途</th><th>状态</th><th>实际 Span</th></tr></thead><tbody>
        <tr v-for="item in datasets.items.value" :key="item.dataset_id"><td><a :href="link('data', { dataset: item.dataset_id })">{{ item.name }}</a></td>
          <td>{{ item.purpose }}</td><td>{{ item.state }}</td><td>{{ count(item.actual_counts.spans ?? null) }}</td></tr>
      </tbody></table></div>
    </LoadState>
    <CursorNav :back="!!datasets.trail.value.length" :forward="!!datasets.nextCursor.value" :loading="datasets.loading.value" @previous="datasets.previous" @next="datasets.next" />
    <LoadState v-if="datasetId" :loading="dataset.loading.value" :error="dataset.error.value" @retry="dataset.load(signal => v2.dataset(datasetId!, signal))">
      <JsonDetails v-if="dataset.data.value" label="清单、分布与内容摘要" :value="dataset.data.value" />
    </LoadState>
  </section>
  <section v-if="panel === 'catalog'" class="card">
    <h2>数据库结构</h2>
    <details open>
      <summary>设计关系图</summary>
      <p class="muted">箭头从被引用表指向引用表。下方目录由服务端返回。</p>
      <GraphView :nodes="designNodes" :edges="relations" :selected="tableName" @select="selectTable" />
    </details>
    <LoadState :loading="catalog.loading.value" :error="catalog.error.value" :empty="!catalog.data.value?.tables.length && !catalog.data.value?.views.length" @retry="catalog.load(v2.catalog)">
      <div v-if="catalog.data.value" class="v2-scroll">
        <article v-for="table in catalog.data.value.tables" :id="'v2-table-' + table.name" :key="table.name" :class="['subpanel', { 'v2-selected': table.name === tableName }]">
          <h3>{{ table.name }} <small>{{ count(table.size_bytes) }} B</small></h3>
          <JsonDetails label="列" :value="table.columns" /><JsonDetails label="约束" :value="table.constraints" /><JsonDetails label="索引" :value="table.indexes" />
        </article>
        <JsonDetails v-for="view in catalog.data.value.views" :key="view.name" :label="view.name" :value="view.definition" />
      </div>
    </LoadState>
    <h2>登记的 SQL 模板</h2>
    <LoadState :loading="templates.loading.value" :error="templates.error.value" :empty="!templates.data.value?.length" @retry="templates.load(v2.templates)">
      <details v-for="item in templates.data.value" :key="item.code"><summary>{{ item.code }} · {{ item.description }}</summary>
        <pre>{{ item.sql }}</pre><JsonDetails label="参数和索引" :value="{ parameters: item.parameters, index_names: item.index_names }" /></details>
    </LoadState>
  </section>
  <section v-if="panel === 'audit'" class="card">
    <h2>操作审计</h2>
    <div class="form-grid">
      <label>动作 <input v-model.trim="scope.action" /></label><label>资源类型 <input v-model.trim="scope.resource_type" /></label>
      <label>资源 ID <input v-model.trim="scope.resource_id" /></label>
    </div>
    <TimeFilter @apply="filterAudit" />
    <LoadState :loading="audit.loading.value" :error="audit.error.value" :empty="!audit.items.value.length" @retry="audit.reset()">
      <div class="table-wrap v2-scroll"><table><thead><tr><th>动作</th><th>资源</th><th>详情</th></tr></thead><tbody>
        <tr v-for="(item, index) in audit.items.value" :key="String(item.audit_id ?? index)"><td>{{ item.action }}</td><td>{{ item.resource_type }} · {{ item.resource_id }}</td>
          <td><JsonDetails label="审计记录" :value="item" /></td></tr></tbody></table></div>
    </LoadState>
    <CursorNav :back="!!audit.trail.value.length" :forward="!!audit.nextCursor.value" :loading="audit.loading.value" @previous="audit.previous" @next="audit.next" />
  </section>
  <section class="card">
    <div class="section-heading"><h2>物化视图</h2><button class="secondary" :disabled="refresh.loading.value || !!aggregate.data.value?.refreshing" @click="refreshAggregate">{{ refresh.loading.value ? '刷新中…' : '刷新日聚合' }}</button></div>
    <LoadState :loading="aggregate.loading.value" :error="aggregate.error.value" @retry="aggregate.load(v2.aggregate)">
      <p v-if="aggregate.data.value">快照 {{ time(aggregate.data.value.snapshot_at) }} · 水位 {{ aggregate.data.value.watermark_max_seq }} · {{ aggregate.data.value.refreshing ? '刷新中' : aggregate.data.value.stale ? '待更新' : '已同步' }}</p>
    </LoadState>
    <p v-if="refresh.error.value" class="error" role="alert">{{ refresh.error.value }}</p>
  </section>
</template>
