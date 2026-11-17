<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import LoadState from '../components/LoadState.vue'
import { errorMessage, useRequest } from '../composables/requests'
import TracePage from '../pages/TracePage.vue'
import { ms, time } from '../utils/format'
import { v2 } from './api'
import GraphView from './GraphView.vue'
import JsonDetails from './JsonDetails.vue'
import Waterfall from './Waterfall.vue'
import { fillJournal, project, replayBase, watchRun } from './journal'
import type { Definition, JournalEvent, Snapshot } from './types'

const props = defineProps<{ runId?: string; spanId?: string; eventId?: string }>()
const snapshot = shallowRef<Snapshot>()
const definition = shallowRef<Definition>()
const journal = shallowRef<JournalEvent[]>([])
const connection = ref('')
const streamError = ref('')
const id = ref(props.runId ?? '')
const legacy = ref(false)
const tab = ref<'graph' | 'waterfall' | 'journal' | 'analysis'>('graph')
const selectedId = ref(props.spanId ?? '')
const logicalId = ref('')
const ownership = ref(false)
const table = ref(false)
const collapsed = ref<string[]>([])
const focusedSeq = ref<number>()
const replay = ref<number>()
const speed = ref(1)
const playing = ref(false)
const main = useRequest<{ legacy: true } | { legacy: false; initial: Snapshot; definition: Definition }>()
const history = useRequest<boolean>()
const analysis = useRequest<Awaited<ReturnType<typeof v2.analysis>>>()
let controller: AbortController | undefined
let replayTimer: ReturnType<typeof setTimeout> | undefined

const view = computed(() => replay.value === undefined || !snapshot.value || !definition.value
  ? snapshot.value
  : project(replayBase(snapshot.value.run, definition.value), journal.value.slice(0, replay.value)))
const selected = computed(() => view.value?.spans.find(span => span.span_id === selectedId.value))
const graphNodes = computed(() => ownership.value
  ? (view.value?.spans ?? []).filter(span => !span.role_key || !collapsed.value.includes(span.role_key) || span.node_key === null)
    .map(span => ({ id: span.span_id, label: span.span_name, status: span.state, caption: span.node_key ?? span.operation_type }))
  : (definition.value?.nodes ?? []).map(node => ({
    id: node.node_key, label: node.name, caption: node.type,
    status: view.value?.nodes.find(item => item.node_key === node.node_key)?.state ?? 'PENDING',
  })))
const graphEdges = computed(() => ownership.value
  ? (view.value?.spans ?? []).filter(span => span.parent_span_id).map(span => ({ source: span.parent_span_id!, target: span.span_id }))
  : (definition.value?.edges ?? []).map(edge => ({ ...edge, label: edge.route === 'ALWAYS' ? undefined : edge.route })))
const path = computed(() => {
  const logicalPath = analysis.data.value?.critical_path?.node_keys ?? []
  const keys = new Set(logicalPath)
  return ownership.value
    ? (view.value?.spans ?? []).filter(span => span.node_key && keys.has(span.node_key)).map(span => span.span_id)
    : logicalPath
})
const attempts = computed(() => view.value?.spans.filter(span => span.node_key && span.node_key === logicalId.value) ?? [])
const visibleJournal = computed(() => {
  const limit = replay.value ?? snapshot.value?.seq ?? 0
  return journal.value.filter(event => event.seq <= limit)
})
const spanEvents = computed(() => visibleJournal.value.flatMap(event =>
  event.kind === 'span.event' && event.payload.span_id === selectedId.value ? [event.payload] : []))
const lastTime = computed(() => replay.value === undefined ? journal.value.at(-1)?.occurred_at : journal.value[replay.value - 1]?.occurred_at)
const historyComplete = computed(() => journal.value.length === snapshot.value?.seq && journal.value.every((event, index) => event.seq === index + 1))

function selectSpan(spanId: string) {
  selectedId.value = spanId
  logicalId.value = view.value?.spans.find(span => span.span_id === spanId)?.node_key ?? ''
}
function selectNode(key: string) {
  if (ownership.value) { selectSpan(key); return }
  logicalId.value = key
  selectedId.value = view.value?.nodes.find(node => node.node_key === key)?.span_ids.at(-1) ?? ''
}
function selectEvent(event: JournalEvent) {
  focusedSeq.value = event.seq
  if (event.kind === 'span.event' || event.kind === 'span.started' || event.kind === 'span.finished') selectSpan(event.payload.span_id)
  if (event.kind === 'node.skipped') selectNode(event.payload.node_key)
}
function stopReplay() { playing.value = false; clearTimeout(replayTimer) }
function tick() {
  if (!playing.value || replay.value === undefined || replay.value >= journal.value.length) { stopReplay(); return }
  const next = journal.value[replay.value]
  const previous = journal.value[replay.value - 1]
  const gap = previous ? Date.parse(next.occurred_at) - Date.parse(previous.occurred_at) : 0
  replayTimer = setTimeout(() => { replay.value = replay.value! + 1; tick() }, Math.max(16, gap / speed.value))
}
function beginReplay() {
  if (!historyComplete.value) return
  if (playing.value) { stopReplay(); return }
  if (replay.value === undefined || replay.value === journal.value.length) replay.value = 0
  playing.value = true
  tick()
}
function jump(seq: number) { if (historyComplete.value) { stopReplay(); replay.value = seq } }
function live() { stopReplay(); replay.value = undefined }

async function loadAnalysis() {
  if (props.runId && snapshot.value?.run.status !== 'RUNNING') {
    await analysis.load(signal => v2.analysis(props.runId!, signal))
  }
}
async function loadHistory(runId: string, seq: number) {
  await history.load(async signal => {
    let records: JournalEvent[] = []
    await fillJournal(runId, 0, seq, signal, events => { records.push(...events) })
    signal.throwIfAborted()
    // Live events can arrive concurrently with the historical prefix.
    records = records.concat(journal.value.filter(event => event.seq > seq))
    journal.value = records
    const target = records.find(event => event.kind === 'span.event' && event.payload.event_id === props.eventId)
    if (target) focusedSeq.value = target.seq
    return true
  })
}
async function connect(runId: string) {
  controller?.abort()
  const own = new AbortController()
  controller = own
  const signal = own.signal
  streamError.value = ''
  connection.value = '连接中'
  live()
  journal.value = []
  snapshot.value = undefined
  definition.value = undefined
  analysis.cancel()
  analysis.data.value = null
  history.cancel()
  legacy.value = false
  const ready = await main.load(async () => {
    const run = await v2.run(runId, signal)
    if (run.mode === 'LEGACY') return { legacy: true }
    if (!run.version_id) throw new Error('运行缺少工作流版本')
    const [initial, version] = await Promise.all([v2.snapshot(runId, signal), v2.version(run.version_id, signal)])
    signal.throwIfAborted()
    return { legacy: false, initial, definition: version.definition }
  })
  if (!ready || signal.aborted) return
  legacy.value = ready.legacy
  if (ready.legacy) return
  definition.value = ready.definition
  snapshot.value = ready.initial
  if (props.spanId) selectSpan(props.spanId)
  void loadHistory(runId, ready.initial.seq)
  try {
    await watchRun(runId, signal, {
      snapshot: () => snapshot.value!,
      reset: next => {
        snapshot.value = next
        void loadHistory(runId, next.seq)
      },
      append: event => {
        snapshot.value = project(snapshot.value!, [event])
        journal.value = [...journal.value, event]
      },
      connection: label => { connection.value = label },
    })
    signal.throwIfAborted()
    const final = await v2.snapshot(runId, signal)
    if (!signal.aborted) {
      snapshot.value = final
      if (journal.value.length !== final.seq && !history.loading.value) void loadHistory(runId, final.seq)
      void loadAnalysis()
    }
  } catch (cause) {
    if (!signal.aborted) { streamError.value = errorMessage(cause); connection.value = '已断开' }
  }
}
function openRun() {
  if (id.value.trim()) location.hash = '#/analysis?run=' + encodeURIComponent(id.value.trim())
}
watch(speed, () => { if (playing.value) { clearTimeout(replayTimer); tick() } })
onMounted(() => { if (props.runId) void connect(props.runId) })
onBeforeUnmount(() => { controller?.abort(); stopReplay() })
</script>

<template>
  <header class="page-heading"><h1>轨迹分析</h1><p>工作流拓扑、Span 归属、持久事件与执行时长。</p></header>
  <section v-if="!runId" class="card">
    <form class="actions" @submit.prevent="openRun"><label>Run ID <input v-model.trim="id" required /></label><button>打开运行</button></form>
    <p><a href="#/run-center">从运行中心选择</a></p>
  </section>
  <template v-else-if="legacy">
    <p class="subpanel">LEGACY · 静态轨迹。当前记录只有已保存的完成数据。</p>
    <TracePage :run-id="runId" :span-id="spanId" :event-id="eventId" />
  </template>
  <LoadState v-else-if="runId" :loading="main.loading.value" :error="main.error.value" @retry="connect(runId!)">
    <template v-if="view">
      <section class="card v2-run-summary">
        <div class="section-heading"><h2>{{ view.run.workflow_name ?? '工作流运行' }}</h2>
          <div class="actions"><span :class="['badge', view.run.status]">{{ view.run.status }}</span><span class="badge">{{ view.run.execution_state }}</span><span class="badge">{{ view.run.mode }}</span></div>
        </div>
        <p><code>{{ view.run.run_id }}</code></p>
        <div class="actions"><span>{{ connection }} · seq {{ view.seq }}</span><span>{{ view.spans.length }} Span · {{ view.event_count }} 事件</span>
          <span>排队 {{ ms(view.run.queue_duration_ms) }} · 执行 {{ ms(view.run.execution_duration_ms) }} · 逻辑 {{ ms(view.run.logical_duration_ms) }}</span>
        </div>
        <p v-if="view.run.error_summary" class="error">{{ view.run.error_summary }}</p>
        <p v-if="view.run.status !== 'RUNNING' && !view.projection_complete" class="notice error">轨迹不完整。可查看已保存的执行日志。</p>
        <p v-if="streamError" role="alert" class="error">{{ streamError }} <button class="secondary" @click="connect(runId!)">重新连接</button></p>
      </section>
      <section class="card">
        <div class="actions v2-tabs" aria-label="轨迹视图">
          <button v-for="[value, label] in ([['graph','拓扑'],['waterfall','时间瀑布'],['journal','事件 / 回放'],['analysis','耗时分析']] as const)" :key="value"
            class="secondary" :aria-pressed="tab === value" @click="tab = value">{{ label }}</button>
        </div>
        <div v-if="tab === 'graph'">
          <div class="actions v2-toolbar">
            <button class="secondary" :aria-pressed="!ownership" @click="ownership = false">依赖 DAG</button>
            <button class="secondary" :aria-pressed="ownership" @click="ownership = true">Span 归属树</button>
            <button class="secondary" :aria-pressed="table" @click="table = !table">列表视图</button>
          </div>
          <div v-if="ownership" class="actions">
            <label v-for="role in definition?.roles" :key="role.role_key" class="check"><input v-model="collapsed" type="checkbox" :value="role.role_key" />折叠 {{ role.name }}</label>
          </div>
          <p class="muted">橙色连线表示理论关键路径，红色边框和 ERROR 标签表示失败节点。</p>
          <GraphView v-if="!table" :nodes="graphNodes" :edges="graphEdges" :selected="ownership ? selectedId : logicalId" :highlight="path" :highlight-links="!ownership" @select="selectNode" />
          <div v-else class="table-wrap v2-scroll"><table><thead><tr><th>节点</th><th>类型</th><th>状态</th></tr></thead>
            <tbody><tr v-for="node in graphNodes" :key="node.id"><td><button class="link-button" @click="selectNode(node.id)">{{ node.label }}</button></td><td>{{ node.caption }}</td><td>{{ node.status }}</td></tr></tbody>
          </table></div>
        </div>
        <Waterfall v-else-if="tab === 'waterfall'" :spans="view.spans" :selected="selectedId" :through="lastTime" @select="selectSpan" />
        <div v-else-if="tab === 'journal'">
          <LoadState :loading="history.loading.value" :error="history.error.value" :empty="!journal.length" @retry="loadHistory(runId!, snapshot!.seq)">
            <div class="actions v2-toolbar">
              <button class="secondary" :disabled="!historyComplete" @click="beginReplay">{{ playing ? '暂停' : '播放' }}</button>
              <label>速度 <select v-model.number="speed"><option v-for="rate in [.5, 1, 2, 4]" :key="rate" :value="rate">{{ rate }}×</option></select></label>
              <label>回放序号 <input type="range" :disabled="!historyComplete" :value="replay ?? journal.length" min="0" :max="journal.length" @input="jump(Number(($event.target as HTMLInputElement).value))" /></label>
              <button class="secondary" @click="live">返回最新</button>
            </div>
            <div class="table-wrap v2-scroll"><table><thead><tr><th>序号</th><th>类型</th><th>时间</th><th>数据</th></tr></thead><tbody>
              <tr v-for="event in visibleJournal" :key="event.seq" :class="{ 'v2-selected': focusedSeq === event.seq }">
                <td><button class="link-button" @click="selectEvent(event)">{{ event.seq }}</button></td><td>{{ event.kind }}</td><td>{{ time(event.occurred_at) }}</td><td><JsonDetails label="查看事件" :value="event.payload" /></td>
              </tr>
            </tbody></table></div>
          </LoadState>
        </div>
        <div v-else>
          <p v-if="view.run.status === 'RUNNING'">运行结束后可查看耗时分析。</p>
          <LoadState v-else :loading="analysis.loading.value" :error="analysis.error.value" @retry="loadAnalysis">
            <div v-if="analysis.data.value">
              <template v-if="analysis.data.value.supported !== false">
                <p>算法 {{ analysis.data.value.algorithm_version }} · 数据水位 {{ analysis.data.value.journal_seq }} · {{ analysis.data.value.time_basis }}</p>
                <dl><dt>理论关键路径</dt><dd>{{ ms(analysis.data.value.critical_path?.duration_ms ?? null) }} · {{ analysis.data.value.critical_path?.node_keys.join(' → ') }}</dd>
                  <dt>重试累计工作量</dt><dd>{{ ms(analysis.data.value.retry_overhead_ms) }}</dd><dt>调度等待</dt><dd>{{ ms(analysis.data.value.scheduler_wait_ms) }}</dd>
                  <dt>恢复停顿估计</dt><dd>{{ ms(analysis.data.value.recovery_pause_ms) }}</dd></dl>
                <JsonDetails label="Span 自耗时（ms）" :value="analysis.data.value.self_times" />
                <ul><li v-for="(finding, i) in analysis.data.value.findings" :key="i">{{ finding.severity }} · {{ finding.explanation }}<JsonDetails label="分析证据" :value="finding.evidence" /></li></ul>
                <ul><li v-for="item in analysis.data.value.limitations" :key="item">{{ item }}</li></ul>
              </template>
              <p v-else>{{ analysis.data.value.reason }}</p>
            </div>
          </LoadState>
        </div>
      </section>
      <section v-if="logicalId || selected" class="card v2-inspector" aria-label="节点和 Span 详情">
        <div class="section-heading"><h2>{{ logicalId || selected?.span_name }}</h2><button class="secondary" @click="logicalId = selectedId = ''">关闭详情</button></div>
        <p v-if="!selected">该节点在当前水位暂时没有 Span。</p>
        <div v-if="attempts.length" class="actions"><button v-for="attempt in attempts" :key="attempt.span_id" class="secondary" :aria-pressed="attempt.span_id === selectedId" @click="selectSpan(attempt.span_id)">尝试 {{ attempt.attempt_no }} · {{ attempt.state }}</button></div>
        <template v-if="selected">
          <p>{{ selected.span_name }} · {{ selected.state }} · {{ selected.operation_type }}</p>
          <dl><dt>Span ID</dt><dd>{{ selected.span_id }}</dd><dt>开始 / 结束</dt><dd>{{ time(selected.start_time) }} / {{ time(selected.end_time) }}</dd>
            <dt>Token</dt><dd>{{ selected.input_tokens ?? '—' }} / {{ selected.output_tokens ?? '—' }}</dd><dt>错误</dt><dd>{{ selected.error_message ?? '—' }}</dd></dl>
          <JsonDetails label="Span 全字段" :value="selected" />
          <JsonDetails label="依赖与重试链接" :value="view.links.filter(edge => edge.source_span_id === selectedId || edge.target_span_id === selectedId)" />
          <h3>关联事件</h3><p v-if="!spanEvents.length">当前水位暂无事件。</p>
          <ul><li v-for="event in spanEvents" :key="event.event_id" :class="{ 'v2-selected': event.event_id === eventId }">{{ event.severity }} · {{ event.event_name }} · {{ event.message ?? '—' }}</li></ul>
        </template>
      </section>
    </template>
  </LoadState>
</template>
