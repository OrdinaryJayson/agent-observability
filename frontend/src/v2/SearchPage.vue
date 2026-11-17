<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import LoadState from '../components/LoadState.vue'
import { errorMessage } from '../composables/requests'
import { time, utcWindow } from '../utils/format'
import { v2, type Filters } from './api'
import CursorNav from './CursorNav.vue'
import JsonDetails from './JsonDetails.vue'
import { link, localTime, traceLink, useCursor } from './state'

const props = defineProps<{ search: string }>()
const params = new URLSearchParams(props.search)
const kind = ref<'spans' | 'events'>(params.get('kind') === 'spans' ? 'spans' : 'events')
const shared = ['task_id', 'run_id', 'agent_id', 'error_type', 'from', 'to'] as const
const specific = { spans: ['status', 'type', 'attributes', 'q'], events: ['severity', 'trace_id', 'mode'] }
const keys = [...shared, ...specific.events, ...specific.spans]
const form = reactive(Object.fromEntries(keys.map(key => [key, key === 'from' || key === 'to' ? localTime(params.get(key)) : params.get(key) ?? ''])))
const error = ref('')
const applied = ref<Filters>(Object.fromEntries([...params].filter(([key]) => [...shared, ...specific[kind.value]].includes(key))))
const list = useCursor((cursor, signal) => v2.search(kind.value, applied.value, cursor, signal))
function apply() {
  error.value = ''
  try {
    const window = utcWindow(form.from, form.to)
    const fields = Object.fromEntries([...shared, ...specific[kind.value]].map(key => [key, form[key].trim()]))
    if (kind.value === 'spans' && fields.attributes) {
      const parsed = JSON.parse(fields.attributes)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('属性过滤必须是 JSON 对象')
      fields.attributes = JSON.stringify(parsed)
      if (new TextEncoder().encode(fields.attributes).length > 2048) throw new Error('属性过滤最多 2 KiB')
    }
    const href = link('search', { kind: kind.value, ...fields, ...window })
    if (location.hash === href) void list.reset()
    else location.hash = href
  } catch (cause) { error.value = errorMessage(cause) }
}
function switchKind() {
  location.hash = link('search', { kind: kind.value })
}
onMounted(() => void list.load())
</script>

<template>
  <header class="page-heading"><h1>日志检索</h1><p>按业务标识、时间与属性查找事件或 Span，定位对应轨迹。</p></header>
  <section class="card"><h2>组合筛选</h2><form class="filter-row" @submit.prevent="apply">
    <label>资源 <select v-model="kind" @change="switchKind"><option value="events">事件</option><option value="spans">Span</option></select></label>
    <label>Task ID <input v-model="form.task_id" /></label><label>Run ID <input v-model="form.run_id" /></label><label>Agent ID <input v-model="form.agent_id" /></label>
    <label>错误类型 <input v-model="form.error_type" maxlength="100" /></label>
    <template v-if="kind === 'spans'">
      <label>Span 状态 <select v-model="form.status"><option value="">全部</option><option>SUCCESS</option><option>ERROR</option></select></label>
      <label>操作类型 <select v-model="form.type"><option value="">全部</option><option v-for="type in ['WORKFLOW','AGENT','LLM','TOOL','RETRIEVAL','OTHER']" :key="type">{{ type }}</option></select></label>
      <label>文本 <input v-model="form.q" maxlength="200" /></label><label>属性（JSON） <textarea v-model="form.attributes" rows="1" spellcheck="false" /></label>
    </template>
    <template v-else>
      <label>Trace ID <input v-model="form.trace_id" maxlength="32" /></label>
      <label>等级 <select v-model="form.severity"><option value="">全部</option><option v-for="severity in ['TRACE','DEBUG','INFO','WARN','ERROR']" :key="severity">{{ severity }}</option></select></label>
      <label>时钟模式 <select v-model="form.mode"><option value="">全部</option><option>REALTIME</option><option>VIRTUAL</option><option>LEGACY</option></select></label>
    </template>
    <label>开始时间 <input v-model="form.from" type="datetime-local" step="0.001" /></label><label>结束时间 <input v-model="form.to" type="datetime-local" step="0.001" /></label>
    <div class="actions"><button>检索</button><a :href="link('search', { kind })">清空</a></div>
    <small>应用后可直接分享地址栏链接。结束时间不包含在结果中。</small>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </form></section>
  <section class="card"><h2>检索结果</h2>
    <LoadState :loading="list.loading.value" :error="list.error.value" :empty="!list.items.value.length" @retry="list.reset()">
      <div class="table-wrap v2-scroll"><table><thead><tr><th>名称</th><th>状态 / 等级</th><th>时间</th><th>轨迹</th><th>数据</th></tr></thead><tbody>
        <tr v-for="row in list.items.value" :key="row.event_id ?? row.run_id + ':' + row.span_id">
          <td>{{ row.event_name ?? row.span_name }}<small>{{ row.message }}</small></td><td>{{ row.severity ?? row.status }}</td>
          <td>{{ time(row.occurred_at ?? row.start_time ?? null) }}</td><td><a :href="traceLink(row.run_id, row.span_id, row.event_id)">定位轨迹</a></td>
          <td><JsonDetails label="记录详情" :value="row" /></td>
        </tr>
      </tbody></table></div>
    </LoadState>
    <CursorNav :back="!!list.trail.value.length" :forward="!!list.nextCursor.value" :loading="list.loading.value" @previous="list.previous" @next="list.next" />
  </section>
</template>
