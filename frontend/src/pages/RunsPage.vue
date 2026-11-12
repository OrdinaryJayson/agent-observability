<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api/client'
import LoadState from '../components/LoadState.vue'
import PageNav from '../components/PageNav.vue'
import { errorMessage, usePage } from '../composables/requests'
import { runSources, runStatuses, type RunFilters } from '../types'
import { time, timeZone, utcWindow } from '../utils/format'
import { traceHref } from '../utils/routes'

const props = defineProps<{ initialTaskId?: string }>()
const form = reactive({
  task_id: props.initialTaskId ?? '', status: '' as RunFilters['status'], source_type: '' as RunFilters['source_type'],
  from: '', to: '',
})
const applied = ref<RunFilters>({ task_id: form.task_id })
const validation = ref('')
const { items, meta, loading, error, load } = usePage((page, signal) => api.runs(page, applied.value, signal))

function apply() {
  validation.value = ''
  try {
    const window = utcWindow(form.from, form.to)
    applied.value = {
      task_id: form.task_id.trim(), status: form.status, source_type: form.source_type,
      start_time: window.from, end_time: window.to,
    }
    void load(1)
  } catch (cause) {
    validation.value = errorMessage(cause)
  }
}

function clear() {
  Object.assign(form, { task_id: '', status: '', source_type: '', from: '', to: '' })
  apply()
}

onMounted(() => void load())
</script>

<template>
  <header class="page-heading">
    <p class="eyebrow">RUNS</p>
    <h1>运行历史</h1>
    <p>按任务、来源、状态或开始时间查找运行记录。</p>
  </header>
  <section class="card">
    <h2>筛选运行</h2>
    <form class="filter-row" @submit.prevent="apply">
      <label>Task ID <input v-model="form.task_id" /></label>
      <label>运行状态 <select v-model="form.status"><option value="">全部</option><option v-for="status in runStatuses" :key="status">{{ status }}</option></select></label>
      <label>运行来源 <select v-model="form.source_type"><option value="">全部</option><option v-for="source in runSources" :key="source">{{ source }}</option></select></label>
      <label>开始时间 <input v-model="form.from" type="datetime-local" /></label>
      <label>结束时间 <input v-model="form.to" type="datetime-local" /></label>
      <div class="actions"><button>筛选运行</button><button type="button" class="secondary" @click="clear">清空筛选</button></div>
      <small>本地时间 · {{ timeZone }} · 结束时间不包含在内</small>
      <p v-if="validation" role="alert" class="error">{{ validation }}</p>
    </form>
  </section>
  <section class="card">
    <h2>运行记录</h2>
    <LoadState :loading="loading" :error="error" :empty="!items.length" empty-text="没有符合条件的运行。" @retry="load()">
      <div class="table-wrap">
        <table>
          <thead><tr><th>Run ID / Task ID</th><th>来源</th><th>状态</th><th>起止时间</th><th>Trace</th></tr></thead>
          <tbody>
            <tr v-for="run in items" :key="run.run_id">
              <td><code>{{ run.run_id }}</code><small>{{ run.task_id }}</small></td>
              <td>{{ run.source_type }}</td><td><span :class="['badge', run.status]">{{ run.status }}</span></td>
              <td>{{ time(run.started_at) }}<small>{{ time(run.ended_at) }}</small></td>
              <td><a :href="traceHref(run.run_id)">查看 Trace</a><small><code>{{ run.trace_id }}</code></small></td>
            </tr>
          </tbody>
        </table>
      </div>
    </LoadState>
    <PageNav v-if="meta" :meta="meta" label="运行分页" @change="load" />
  </section>
</template>
