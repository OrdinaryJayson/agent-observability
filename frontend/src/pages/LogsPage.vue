<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api/client'
import LoadState from '../components/LoadState.vue'
import PageNav from '../components/PageNav.vue'
import { errorMessage, usePage } from '../composables/requests'
import { severities, type EventFilters } from '../types'
import { time, timeZone, utcWindow } from '../utils/format'
import { traceHref } from '../utils/routes'

const blank = () => ({ severity: '' as EventFilters['severity'], task_id: '', agent_id: '', run_id: '',
  trace_id: '', error_type: '', from: '', to: '' })
const form = reactive(blank())
const applied = ref<EventFilters>({})
const validation = ref('')
const { items, meta, loading, error, load } = usePage((page, signal) => api.logs(page, applied.value, signal))

function apply() {
  validation.value = ''
  try {
    applied.value = {
      ...utcWindow(form.from, form.to),
      severity: form.severity, task_id: form.task_id.trim(), agent_id: form.agent_id.trim(),
      run_id: form.run_id.trim(), trace_id: form.trace_id.trim(), error_type: form.error_type.trim(),
    }
    void load(1)
  } catch (cause) {
    validation.value = errorMessage(cause)
  }
}

function clear() {
  Object.assign(form, blank())
  apply()
}

onMounted(() => void load())
</script>

<template>
  <header class="page-heading">
    <p class="eyebrow">EVENTS</p>
    <h1>全局日志</h1>
    <p>跨运行查找事件，并打开相关 Trace 和 Span。</p>
  </header>
  <section class="card">
    <h2>筛选日志</h2>
    <form class="filter-row" @submit.prevent="apply">
      <label>日志等级 <select v-model="form.severity"><option value="">全部</option><option v-for="level in severities" :key="level">{{ level }}</option></select></label>
      <label>Task ID <input v-model="form.task_id" /></label>
      <label>Agent ID <input v-model="form.agent_id" /></label>
      <label>Run ID <input v-model="form.run_id" /></label>
      <label>Trace ID <input v-model="form.trace_id" /></label>
      <label>错误类型 <input v-model="form.error_type" maxlength="100" /></label>
      <label>开始时间 <input v-model="form.from" type="datetime-local" /></label>
      <label>结束时间 <input v-model="form.to" type="datetime-local" /></label>
      <div class="actions"><button>筛选日志</button><button type="button" class="secondary" @click="clear">清空筛选</button></div>
      <small>本地时间 · {{ timeZone }} · 结束时间不包含在内</small>
      <p v-if="validation" role="alert" class="error">{{ validation }}</p>
    </form>
  </section>
  <section class="card">
    <h2>日志记录</h2>
    <LoadState :loading="loading" :error="error" :empty="!items.length" empty-text="没有符合条件的日志。" @retry="load()">
      <div class="table-wrap">
        <table>
          <thead><tr><th>时间 / 等级</th><th>事件 / 消息</th><th>任务 / Agent</th><th>轨迹定位</th></tr></thead>
          <tbody>
            <tr v-for="event in items" :key="event.event_id">
              <td>{{ time(event.occurred_at) }}<small><span :class="['badge', event.severity]">{{ event.severity }}</span></small></td>
              <td>
                <strong>{{ event.event_name }}</strong><small>{{ event.message ?? '—' }}</small>
                <details><summary>事件属性</summary><pre>{{ JSON.stringify(event.attributes, null, 2) }}</pre></details>
              </td>
              <td><small>Task · {{ event.task_id }}</small><small>Agent · {{ event.agent_id ?? '—' }}</small></td>
              <td>
                <a :href="traceHref(event.run_id, event.span_id, event.event_id)">定位 Trace</a>
                <small>Trace · {{ event.trace_id }}</small><small>Run · {{ event.run_id }}</small>
                <small>Span · {{ event.span_id }}</small><small>Event · {{ event.event_id }}</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </LoadState>
    <PageNav v-if="meta" :meta="meta" label="日志分页" @change="load" />
  </section>
</template>
