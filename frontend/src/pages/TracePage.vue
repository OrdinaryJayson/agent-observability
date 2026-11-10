<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api/client'
import { errorMessage } from '../composables/requests'
import type { Run, Span, SpanEvent, Trace } from '../types'
import { count, ms, time } from '../utils/format'
import { flattenTree, spanTimeline } from '../utils/tree'
import { traceHref } from '../utils/routes'

const props = defineProps<{ quick?: boolean; runId?: string; spanId?: string; eventId?: string }>()
const title = ref('AI Agent 技术调研')
const fail = ref(false)
const busy = ref(false)
const error = ref('')
const run = ref<Run | null>(null)
const trace = ref<Trace | null>(null)
const spans = ref<Span[]>([])
const events = ref<SpanEvent[]>([])
const selectedId = ref('')
const selectedOnly = ref(false)
const resumeId = ref(props.runId || localStorage.getItem('last-run-id') || '')
const rows = computed(() => flattenTree(spans.value))
const timeline = computed(() => spanTimeline(spans.value))
const selected = computed(() => spans.value.find(span => span.span_id === selectedId.value))
const visibleEvents = computed(() => selectedOnly.value
  ? events.value.filter(event => event.span_id === selectedId.value)
  : events.value)
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined

function begin() {
  clearTimeout(timer)
  controller?.abort()
  controller = new AbortController()
  error.value = ''
  run.value = trace.value = null
  spans.value = []
  events.value = []
  selectedId.value = ''
  selectedOnly.value = false
  busy.value = true
  return controller.signal
}

async function refresh(id: string, signal: AbortSignal) {
  try {
    const response = await api.run(id, signal)
    if (signal.aborted) return
    run.value = response.data
    if (run.value.status === 'RUNNING') {
      timer = setTimeout(() => void refresh(id, signal), 2000)
      return
    }
    const traceId = run.value.trace_id
    const [summary, items, logs] = await Promise.all([
      api.trace(traceId, signal), api.spans(traceId, signal), api.events(traceId, signal),
    ])
    if (signal.aborted) return
    if (items.length !== summary.data.span_count) {
      throw new Error('Span 分页结果与轨迹总数不一致')
    }
    flattenTree(items)
    trace.value = summary.data
    spans.value = items
    events.value = logs
    const target = id === props.runId && items.find(span => span.span_id === props.spanId)
    selectedId.value = (target || items.find(span => span.parent_span_id === null))?.span_id ?? ''
    selectedOnly.value = !!target
    busy.value = false
  } catch (cause) {
    if (!signal.aborted) {
      error.value = errorMessage(cause)
      busy.value = false
    }
  }
}

async function start() {
  if (busy.value || !title.value.trim()) return
  const signal = begin()
  try {
    const task = await api.createTask({ title: title.value.trim() }, signal)
    if (signal.aborted) return
    const accepted = await api.startRun(task.data.task_id, { failure_rate: fail.value ? 1 : 0 }, signal)
    if (signal.aborted) return
    resumeId.value = accepted.data.run_id
    localStorage.setItem('last-run-id', resumeId.value)
    await refresh(resumeId.value, signal)
  } catch (cause) {
    if (!signal.aborted) {
      error.value = errorMessage(cause)
      busy.value = false
    }
  }
}

function resume() {
  const id = resumeId.value.trim()
  if (!id || busy.value) return
  if (!props.quick && id !== props.runId) {
    location.hash = traceHref(id)
  } else {
    void refresh(id, begin())
  }
}

function select(span: Span) {
  selectedId.value = span.span_id
  selectedOnly.value = true
}

onMounted(() => {
  if (props.runId) void refresh(props.runId, begin())
})
onBeforeUnmount(() => {
  clearTimeout(timer)
  controller?.abort()
})
</script>

<template>
  <header class="page-heading" :class="{ 'quick-hero': quick }">
    <div>
      <p class="eyebrow">{{ quick ? 'SIMULATED RUN' : 'TRACE INSPECTOR' }}</p>
      <h1>{{ quick ? '快速模拟执行' : '执行轨迹' }}</h1>
      <p>{{ quick ? '创建并执行一个模拟任务，查看状态、调用关系和事件。' : '输入 Run ID，或从运行历史和全局日志打开一条轨迹。' }}</p>
    </div>
    <svg v-if="quick" class="hero-trace" aria-hidden="true" viewBox="0 0 304 144" fill="none">
      <path d="M26 72h54c22 0 20-42 42-42h68m-110 42c22 0 20 42 42 42h102M80 72h159"
        stroke="currentColor" stroke-width="1.5" />
      <path d="M190 30h65M224 114h36M239 72h40" stroke="currentColor" stroke-dasharray="4 5" />
      <g stroke="currentColor" stroke-width="1.5" fill="#102d2b">
        <rect x="12" y="62" width="25" height="20" rx="5" />
        <rect x="173" y="20" width="35" height="20" rx="5" />
        <rect x="215" y="62" width="36" height="20" rx="5" />
        <rect x="205" y="104" width="36" height="20" rx="5" />
      </g>
      <g fill="#9de1be">
        <circle cx="25" cy="72" r="2.5" /><circle cx="80" cy="72" r="3" />
        <circle cx="190" cy="30" r="2.5" /><circle cx="233" cy="72" r="2.5" /><circle cx="223" cy="114" r="2.5" />
      </g>
    </svg>
  </header>
  <section class="card execution-card">
    <div :class="{ 'execution-grid': quick }">
      <form v-if="quick" @submit.prevent="start">
        <h2>启动模拟执行</h2>
        <label for="title">任务名称</label>
        <div class="input-row">
          <input id="title" v-model="title" required maxlength="200" :disabled="busy" />
          <button :disabled="busy || !title.trim()">{{ busy ? '正在执行或查询…' : '创建并执行' }}</button>
        </div>
        <label class="check"><input v-model="fail" type="checkbox" :disabled="busy" />生成工具失败场景</label>
      </form>
      <form :class="{ resume: quick }" @submit.prevent="resume">
        <h2>恢复运行</h2>
        <label for="run-id">恢复查询已有 Run</label>
        <div class="input-row">
          <input id="run-id" v-model="resumeId" placeholder="Run ID" :disabled="busy" />
          <button class="secondary" :disabled="busy || !resumeId.trim()">查询 / 重试</button>
        </div>
      </form>
    </div>
    <p v-if="busy && !run" role="status">正在执行或查询…</p>
    <p v-if="error" role="alert" class="error">{{ error }}。可使用 Run ID 重试查询。</p>
  </section>

  <section v-if="run" class="card">
    <div class="section-heading"><h2>运行详情</h2><span :class="['badge', run.status]">{{ run.status }}</span></div>
    <dl>
      <dt>Run ID</dt><dd>{{ run.run_id }}</dd>
      <dt>Task ID</dt><dd>{{ run.task_id }}</dd>
      <dt>Trace ID</dt><dd>{{ run.trace_id }}</dd>
      <dt>来源</dt><dd>{{ run.source_type }}</dd>
      <dt>开始时间</dt><dd>{{ time(run.started_at) }}</dd>
      <dt>结束时间</dt><dd>{{ time(run.ended_at) }}</dd>
      <dt>创建时间</dt><dd>{{ time(run.created_at) }}</dd>
    </dl>
    <p v-if="busy" role="status">{{ run.status === 'RUNNING' ? '正在模拟执行，每 2 秒刷新。' : '正在读取完整轨迹…' }}</p>
    <p v-if="run.error_summary" class="error">{{ run.error_summary }}</p>
    <p v-if="trace">{{ count(trace.span_count) }} 个 Span · {{ count(trace.error_count) }} 个失败 Span · {{ count(events.length) }} 条事件</p>
    <p v-if="trace && !trace.span_count">本次运行没有可用的轨迹数据。</p>
  </section>

  <div v-if="spans.length" class="trace-layout">
    <section class="card">
      <h2>Trace 调用树</h2>
      <div class="tree">
        <button
          v-for="row in rows" :key="row.span.span_id" type="button"
          :class="['tree-row', { selected: selectedId === row.span.span_id }]"
          :aria-pressed="selectedId === row.span.span_id"
          :style="{ paddingLeft: `${12 + Math.min(row.depth, 8) * 12}px` }"
          @click="select(row.span)"
        >
          <span>{{ row.span.span_name }}<small>{{ row.span.operation_type }}</small></span>
          <span><span :class="['badge', row.span.status]">{{ row.span.status }}</span><small>{{ ms(row.span.duration_ms) }}</small></span>
        </button>
      </div>
    </section>

    <section class="card">
      <h2>Span 详情</h2>
      <template v-if="selected">
        <h3>{{ selected.span_name }}</h3>
        <dl>
          <dt>Span ID</dt><dd>{{ selected.span_id }}</dd>
          <dt>父 Span</dt><dd>{{ selected.parent_span_id ?? '根节点' }}</dd>
          <dt>Agent ID</dt><dd>{{ selected.agent_id ?? '—' }}</dd>
          <dt>类型 / 状态</dt><dd>{{ selected.operation_type }} / {{ selected.status }}</dd>
          <dt>开始时间</dt><dd>{{ time(selected.start_time) }}</dd>
          <dt>结束时间</dt><dd>{{ time(selected.end_time) }}</dd>
          <dt>耗时</dt><dd>{{ ms(selected.duration_ms) }}</dd>
          <dt>提供商 / 模型</dt><dd>{{ selected.provider ?? '—' }} / {{ selected.model_name ?? '—' }}</dd>
          <dt>工具</dt><dd>{{ selected.tool_name ?? '—' }}</dd>
          <dt>输入 / 输出 Token</dt><dd>{{ count(selected.input_tokens) }} / {{ count(selected.output_tokens) }}</dd>
          <dt>错误类型</dt><dd>{{ selected.error_type ?? '—' }}</dd>
          <dt>错误信息</dt><dd>{{ selected.error_message ?? '—' }}</dd>
        </dl>
        <details><summary>扩展属性</summary><pre>{{ JSON.stringify(selected.attributes, null, 2) }}</pre></details>
      </template>
    </section>
  </div>

  <section v-if="spans.length" class="card">
    <h2>Span 相对时间线</h2>
    <p class="muted">从最早的 Span 开始计时。条形宽度表示各自持续时间。时间范围 0–{{ ms(timeline.total) }}。</p>
    <div class="timeline" aria-label="Span 相对时间线">
      <button
        v-for="row in timeline.rows" :key="row.span.span_id" type="button"
        :class="['timeline-row', { selected: selectedId === row.span.span_id }]"
        :aria-pressed="selectedId === row.span.span_id" @click="select(row.span)"
      >
        <span>{{ row.span.span_name }}<small>+{{ ms(row.offset) }} · {{ ms(row.duration) }}</small></span>
        <span class="timeline-track" aria-hidden="true">
          <span :class="['timeline-bar', row.span.status]" :style="{ left: row.left + '%', width: row.width + '%' }"></span>
        </span>
      </button>
    </div>
  </section>

  <section v-if="trace" class="card">
    <h2>执行事件</h2>
    <label v-if="selected" class="check"><input v-model="selectedOnly" type="checkbox" /> 仅显示当前 Span 的事件</label>
    <p v-if="!visibleEvents.length">暂无事件。</p>
    <ul v-else class="events">
      <li v-for="event in visibleEvents" :key="event.event_id" :class="{ 'focused-event': run?.run_id === runId && event.event_id === eventId }">
        <span :class="['badge', event.severity]">{{ event.severity }}</span>
        <div>
          <strong>{{ event.event_name }}</strong>
          <p>{{ event.message ?? '—' }}</p>
          <small>{{ time(event.occurred_at) }} · {{ event.span_id }}</small>
          <details><summary>事件属性</summary><pre>{{ JSON.stringify(event.attributes, null, 2) }}</pre></details>
        </div>
      </li>
    </ul>
  </section>
  <p v-if="!run && !busy && !error" class="empty">{{ quick ? '创建一次任务，开始查看执行轨迹。' : '暂无轨迹，请输入 Run ID。' }}</p>
</template>
