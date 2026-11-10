<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { api } from './api/client'
import type { Run, Span, SpanEvent, Trace } from './types'
import { flattenTree } from './utils/tree'

const title = ref('AI Agent 技术调研')
const fail = ref(false)
const busy = ref(false)
const error = ref('')
const run = ref<Run | null>(null)
const trace = ref<Trace | null>(null)
const spans = ref<Span[]>([])
const events = ref<SpanEvent[]>([])
const selected = ref<Span | null>(null)
const resumeId = ref(localStorage.getItem('last-run-id') || '')
const rows = computed(() => flattenTree(spans.value))
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined
let disposed = false

function resetRequests() {
  clearTimeout(timer)
  controller?.abort()
  controller = new AbortController()
  return controller.signal
}

async function refresh(id: string, signal: AbortSignal) {
  try {
    run.value = (await api.run(id, signal)).data
    if (run.value.status === 'RUNNING') {
      timer = setTimeout(() => void refresh(id, signal), 2000)
      return
    }
    const traceId = run.value.trace_id
    const [summary, items, logs] = await Promise.all([
      api.trace(traceId, signal), api.spans(traceId, signal), api.events(traceId, signal),
    ])
    flattenTree(items) // Validate before changing the reactive view.
    trace.value = summary.data
    spans.value = items
    events.value = logs
    selected.value = items.find(s => s.parent_span_id === null) || null
    busy.value = false
  } catch (exc) {
    if (!signal.aborted && !disposed) {
      error.value = exc instanceof Error ? exc.message : '请求失败'
      busy.value = false
    }
  }
}

async function start() {
  error.value = ''
  trace.value = null
  spans.value = []
  events.value = []
  selected.value = null
  run.value = null
  busy.value = true
  const signal = resetRequests()
  try {
    const task = await api.createTask(title.value.trim(), signal)
    const accepted = await api.startRun(task.data.task_id, fail.value, signal)
    resumeId.value = accepted.data.run_id
    localStorage.setItem('last-run-id', resumeId.value)
    await refresh(resumeId.value, signal)
  } catch (exc) {
    if (!signal.aborted) {
      error.value = exc instanceof Error ? exc.message : '请求失败'
      busy.value = false
    }
  }
}

function resume() {
  if (!resumeId.value.trim()) return
  error.value = ''
  run.value = null
  trace.value = null
  spans.value = []
  events.value = []
  selected.value = null
  busy.value = true
  void refresh(resumeId.value.trim(), resetRequests())
}

onBeforeUnmount(() => { disposed = true; clearTimeout(timer); controller?.abort() })
</script>

<template>
  <main>
    <header><p class="eyebrow">AGENT OBSERVABILITY / 原型</p><h1>让每一次执行都有迹可循</h1><p>创建模拟任务，查看运行状态、调用关系与执行事件。</p></header>
    <section class="card">
      <h2>启动模拟执行</h2>
      <form @submit.prevent="start">
        <label for="title">任务名称</label>
        <div class="input-row"><input id="title" v-model="title" required maxlength="200" :disabled="busy" /><button :disabled="busy || !title.trim()">{{ busy ? '正在执行或查询…' : '创建并执行' }}</button></div>
        <label class="check"><input v-model="fail" type="checkbox" :disabled="busy" />生成工具失败场景</label>
      </form>
      <form class="resume" @submit.prevent="resume"><label for="run-id">恢复查询已有 Run</label><div class="input-row"><input id="run-id" v-model="resumeId" placeholder="Run ID" :disabled="busy" /><button class="secondary" :disabled="busy || !resumeId.trim()">查询 / 重试</button></div></form>
      <p v-if="error" role="alert" class="error">{{ error }}。可使用 Run ID 重试查询。</p>
    </section>
    <section v-if="run" class="card">
      <div class="section-heading"><h2>运行详情</h2><span :class="['badge', run.status]">{{ run.status }}</span></div>
      <dl><dt>Run ID</dt><dd>{{ run.run_id }}</dd><dt>Trace ID</dt><dd>{{ run.trace_id }}</dd><dt>开始时间</dt><dd>{{ new Date(run.started_at).toLocaleString() }}</dd></dl>
      <p v-if="run.status === 'RUNNING'">正在模拟执行，每 2 秒刷新。执行结束后显示完整轨迹。</p>
      <p v-if="run.error_summary" class="error">{{ run.error_summary }}</p>
      <p v-if="trace">{{ trace.span_count }} 个 Span · {{ trace.error_count }} 个失败 Span · {{ events.length }} 条事件</p>
      <p v-if="trace && !trace.span_count">本次运行没有可用的轨迹数据。</p>
    </section>
    <div v-if="spans.length" class="trace-layout">
      <section class="card"><h2>Trace 调用树</h2><div class="tree"><button v-for="row in rows" :key="row.span.span_id" :class="['tree-row', { selected: selected?.span_id === row.span.span_id }]" :style="{ paddingLeft: `${12 + Math.min(row.depth, 16) * 18}px` }" @click="selected = row.span"><span>{{ row.span.span_name }}<small>{{ row.span.operation_type }}</small></span><span><span :class="['badge', row.span.status]">{{ row.span.status }}</span><small>{{ row.span.duration_ms.toFixed(2) }} ms</small></span></button></div></section>
      <section class="card"><h2>Span 详情</h2><template v-if="selected"><h3>{{ selected.span_name }}</h3><dl><dt>Span ID</dt><dd>{{ selected.span_id }}</dd><dt>父 Span</dt><dd>{{ selected.parent_span_id || '根节点' }}</dd><dt>输入 / 输出 Token</dt><dd>{{ selected.input_tokens ?? '未知 / 不适用' }} / {{ selected.output_tokens ?? '未知 / 不适用' }}</dd><dt>错误信息</dt><dd>{{ selected.error_message || '无' }}</dd></dl><details><summary>完整字段</summary><pre>{{ JSON.stringify(selected, null, 2) }}</pre></details></template></section>
    </div>
    <section v-if="trace" class="card"><h2>执行事件</h2><p v-if="!events.length">暂无事件。</p><ul class="events"><li v-for="event in events" :key="event.event_id"><span :class="['badge', event.severity]">{{ event.severity }}</span><div><strong>{{ event.event_name }}</strong><p>{{ event.message }}</p><small>{{ new Date(event.occurred_at).toLocaleString() }} · {{ event.span_id }}</small></div></li></ul></section>
    <p v-if="!run && !busy" class="empty">创建一次任务，开始查看执行轨迹。</p>
  </main>
</template>
