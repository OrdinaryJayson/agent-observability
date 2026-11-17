<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { allPages, api } from '../api/client'
import LoadState from '../components/LoadState.vue'
import { errorMessage, useRequest } from '../composables/requests'
import type { Agent, Task } from '../types'
import { ms, time, utcWindow } from '../utils/format'
import { v2, type Filters } from './api'
import CursorNav from './CursorNav.vue'
import { link, localTime, traceLink, useCursor, useSubmission } from './state'
import type { Dataset, RunStart, RunView, Version } from './types'

const props = defineProps<{ versionId?: string; search: string }>()
const query = new URLSearchParams(props.search)
const drafts = reactive({
  task_id: query.get('task_id') ?? '', version_id: query.get('version_id') ?? '', status: query.get('status') ?? '',
  execution_state: query.get('execution_state') ?? '', mode: query.get('mode') ?? '',
  from: localTime(query.get('from')), to: localTime(query.get('to')),
})
const filters = ref<Filters>(Object.fromEntries([...query].filter(([key]) => key in drafts)))
const list = useCursor((cursor, signal) => v2.runs(filters.value, cursor, signal))
const resources = useRequest<{ tasks: Task[]; agents: Agent[] }>()
const datasets = useCursor(v2.datasets)
const version = useRequest<Version>()
const action = useRequest<unknown>()
const context = ref('')
const submitError = ref('')
const showLauncher = ref(!!props.versionId)
const taskId = ref('')
const versionId = ref(props.versionId ?? '')
const retryId = ref<string | null>(null)
const start = reactive({ unbound: false, mode: 'REALTIME' as RunStart['mode'], seed: 42, max_parallelism: 4, priority: 0, dataset_id: '' })
const bindings = ref<Record<string, string>>({})
const submission = useSubmission<{ taskId: string; body: RunStart }>('run')

function loadResources() {
  void resources.load(async signal => {
    const [tasks, agents] = await Promise.all([
      allPages(page => api.tasks(page, signal)), allPages(page => api.agents(page, 'ACTIVE', signal)),
    ])
    return { tasks, agents }
  })
}
async function loadVersion() {
  if (!versionId.value.trim()) return
  bindings.value = {}
  await version.load(signal => v2.version(versionId.value.trim(), signal))
}
function apply() {
  submitError.value = ''
  try {
    const next = { ...drafts, ...utcWindow(drafts.from, drafts.to) }
    const href = link('run-center', next)
    if (location.hash === href) void list.reset()
    else location.hash = href
  } catch (cause) { submitError.value = errorMessage(cause) }
}
function launch(retry?: RunView) {
  showLauncher.value = true
  context.value = ''
  if (retry) {
    taskId.value = retry.task_id
    versionId.value = retry.version_id ?? ''
    retryId.value = retry.run_id
    void loadVersion()
  } else {
    retryId.value = null
  }
  if (!resources.data.value && !resources.loading.value) loadResources()
  if (!datasets.data.value && !datasets.loading.value) void datasets.load()
}
async function submit() {
  if (action.loading.value) return
  submitError.value = ''
  const pending = submission.attempt.value
  const chosen = version.data.value
  if (!pending && (!chosen || !taskId.value || chosen.version_id !== versionId.value)) {
    submitError.value = '请选择 Task 并载入已发布版本。'
    return
  }
  const roles = chosen?.definition.roles ?? []
  if (!pending && !start.unbound && roles.some(role => !bindings.value[role.role_key])) {
    submitError.value = '请为每个角色选择 ACTIVE Agent，或选择无绑定模拟。'
    return
  }
  if (!pending && start.mode === 'VIRTUAL' && !start.dataset_id) {
    submitError.value = '虚拟时钟需要指定数据集。'
    return
  }
  const attempt = pending ?? submission.get({ taskId: taskId.value, body: {
    ...start, version_id: chosen!.version_id, dataset_id: start.dataset_id || null,
    retry_of_run_id: retryId.value,
    agent_bindings: start.unbound ? {} : Object.fromEntries(roles.map(role => [role.role_key, bindings.value[role.role_key]])),
  } })
  const result = await action.load(async signal => {
    try {
      const accepted = await v2.start(attempt.payload.taskId, attempt.payload.body, attempt.key, signal)
      submission.clear()
      return accepted
    } catch (error) {
      submission.reject(error)
      throw error
    }
  })
  if (result) location.hash = traceLink((result as Awaited<ReturnType<typeof v2.start>>).run_id)
}
async function cancel(run: RunView) {
  if (action.loading.value) return
  const result = await action.load(signal => v2.cancelRun(run.run_id, signal)) as Awaited<ReturnType<typeof v2.cancelRun>> | undefined
  if (!result) return
  context.value = result.already_terminal ? '运行已先进入终态。' : result.accepted ? '取消请求已接收，等待执行器收尾。' : '取消请求未接受。'
  void list.load()
}
onMounted(() => {
  void list.load()
  if (props.versionId || submission.attempt.value) {
    launch()
    if (props.versionId) void loadVersion()
  }
})
</script>

<template>
  <header class="page-heading"><h1>运行中心</h1><p>查看业务状态和队列状态，启动已发布版本。</p></header>
  <section class="card">
    <form class="filter-row" @submit.prevent="apply">
      <label>Task ID <input v-model.trim="drafts.task_id" /></label>
      <label>版本 ID <input v-model.trim="drafts.version_id" /></label>
      <label>业务状态 <select v-model="drafts.status"><option value="">全部</option><option>RUNNING</option><option>SUCCESS</option><option>FAILED</option><option>CANCELLED</option></select></label>
      <label>执行状态 <select v-model="drafts.execution_state"><option value="">全部</option><option>QUEUED</option><option>RUNNING</option><option>RECOVERING</option><option>FINALIZING</option><option>FINISHED</option></select></label>
      <label>时钟模式 <select v-model="drafts.mode"><option value="">全部</option><option>REALTIME</option><option>VIRTUAL</option><option>LEGACY</option></select></label>
      <label>开始时间 <input v-model="drafts.from" type="datetime-local" step="0.001" /></label>
      <label>结束时间 <input v-model="drafts.to" type="datetime-local" step="0.001" /></label>
      <div class="actions"><button>筛选运行</button><a href="#/run-center">清空</a></div>
    </form>
  </section>

  <section class="card">
    <div class="section-heading"><h2>运行列表</h2><div class="actions"><button class="secondary" @click="list.load()">刷新列表</button><button @click="launch()">启动工作流</button></div></div>
    <LoadState :loading="list.loading.value" :error="list.error.value" :empty="!list.items.value.length" @retry="list.reset()">
      <div class="table-wrap v2-scroll"><table><thead><tr><th>运行</th><th>业务 / 执行</th><th>模式</th><th>排队时间</th><th>排队 / 执行耗时</th><th>操作</th></tr></thead>
        <tbody><tr v-for="run in list.items.value" :key="run.run_id">
          <td><a :href="traceLink(run.run_id)">{{ run.workflow_name ?? run.run_id }}</a><small>版本 {{ run.version_no ?? '—' }}</small></td>
          <td><span :class="['badge', run.status]">{{ run.status }}</span> {{ run.execution_state ?? '—' }}<small v-if="run.cancel_requested_at && run.status === 'RUNNING'">已请求取消</small></td>
          <td>{{ run.mode }}</td><td>{{ time(run.queued_at) }}</td><td>{{ ms(run.queue_duration_ms) }} / {{ ms(run.execution_duration_ms) }}</td>
          <td><button v-if="run.mode !== 'LEGACY' && run.status === 'RUNNING'" class="secondary" :disabled="action.loading.value || !!run.cancel_requested_at" @click="cancel(run)">取消运行</button>
            <button v-else-if="run.version_id && run.status !== 'RUNNING'" class="secondary" @click="launch(run)">再次执行</button></td>
        </tr></tbody></table></div>
    </LoadState>
    <CursorNav :back="!!list.trail.value.length" :forward="!!list.nextCursor.value" :loading="list.loading.value" @previous="list.previous" @next="list.next" />
    <p v-if="context" role="status">{{ context }}</p>
  </section>
  <p v-if="submitError || action.error.value" class="notice error" role="alert">{{ submitError || action.error.value }}</p>

  <section v-if="showLauncher" class="card">
    <h2>{{ retryId ? '再次执行工作流' : '启动工作流' }}</h2>
    <form @submit.prevent="submit">
      <fieldset :disabled="action.loading.value || !!submission.attempt.value">
        <LoadState :loading="resources.loading.value" :error="resources.error.value" @retry="loadResources">
          <div class="form-grid">
            <label>选择 Task <select v-model="taskId" :disabled="!!retryId" required><option value="">请选择</option>
              <option v-for="task in resources.data.value?.tasks" :key="task.task_id" :value="task.task_id">{{ task.title }}</option></select></label>
            <label>工作流版本 <input v-model.trim="versionId" :readonly="!!retryId" required /></label>
            <button type="button" class="secondary" :disabled="version.loading.value || !versionId" @click="loadVersion">载入版本</button>
          </div>
          <p v-if="!resources.data.value?.tasks.length">暂无 Task。<a href="#/tasks">创建任务</a></p>
          <p><a href="#/workflows">从工作流页面选择已发布的版本</a></p>
          <p v-if="version.error.value" class="error" role="alert">{{ version.error.value }}</p>
          <div v-if="version.data.value && version.data.value.version_id === versionId" class="subpanel">
            <p>版本 {{ version.data.value.version_no }} · {{ version.data.value.definition.scenario }}</p>
            <label class="check"><input v-model="start.unbound" type="checkbox" />无绑定模拟</label>
            <div class="form-grid">
              <label v-for="role in start.unbound ? [] : version.data.value.definition.roles" :key="role.role_key">{{ role.name }}
                <select v-model="bindings[role.role_key]" required><option value="">选择 ACTIVE Agent</option>
                  <option v-for="agent in resources.data.value?.agents" :key="agent.agent_id" :value="agent.agent_id">{{ agent.name }}</option></select>
              </label>
              <label>随机种子 <input v-model.number="start.seed" type="number" min="-2147483648" max="2147483647" required /></label>
              <label>并行度 <input v-model.number="start.max_parallelism" type="number" min="1" max="4" required /></label>
              <label>优先级 <input v-model.number="start.priority" type="number" min="-10" max="10" required /></label>
              <label>执行时钟 <select v-model="start.mode"><option>REALTIME</option><option>VIRTUAL</option></select></label>
              <label>数据集 ID <input v-model.trim="start.dataset_id" list="run-datasets" :required="start.mode === 'VIRTUAL'" />
                <datalist id="run-datasets"><option v-for="dataset in datasets.items.value.filter((item: Dataset) => item.state === 'READY')" :key="dataset.dataset_id" :value="dataset.dataset_id">{{ dataset.name }}</option></datalist>
              </label>
            </div>
            <p v-if="!start.unbound && version.data.value.definition.roles.length && !resources.data.value?.agents.length">
              暂无启用 Agent。<a href="#/agents">管理 Agent</a>或选择无绑定模拟。
            </p>
          </div>
        </LoadState>
      </fieldset>
      <div class="actions">
        <button :disabled="action.loading.value || (!submission.attempt.value && (!version.data.value || version.data.value.version_id !== versionId || !taskId))">
          {{ action.loading.value ? '提交中…' : submission.attempt.value ? '重试同一次提交' : '提交运行' }}
        </button>
        <button v-if="submission.attempt.value" type="button" class="secondary" :disabled="action.loading.value" @click="submission.clear()">放弃本次提交记录</button>
      </div>
      <p v-if="submission.attempt.value && !action.loading.value">上次提交结果未知。重试会使用同一个请求键和原参数。</p>
    </form>
  </section>
</template>
