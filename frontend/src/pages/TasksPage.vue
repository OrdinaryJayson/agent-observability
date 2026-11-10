<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api/client'
import LoadState from '../components/LoadState.vue'
import PageNav from '../components/PageNav.vue'
import { usePage, useRequest } from '../composables/requests'
import type { AcceptedRun, Agent, SimulationConfig, Task } from '../types'
import { time } from '../utils/format'
import { traceHref } from '../utils/routes'

const tasks = usePage(api.tasks)
const { items, meta, loading, error, load } = tasks
const active = usePage((page, signal) => api.agents(page, 'ACTIVE', signal))
const taskRequest = useRequest<Task>()
const { data: task, loading: loadingTask, error: taskError } = taskRequest
const createRequest = useRequest<Task>()
const { loading: creating, error: createError } = createRequest
const runRequest = useRequest<AcceptedRun>()
const { loading: starting, error: runError } = runRequest

const title = ref('')
const description = ref('')
const scenario = ref('GENERAL')
const showForm = ref(false)
const taskId = ref('')
const bind = ref(false)
const agents = ref<Agent[]>([])
const validation = ref('')
const config = reactive({ agent_count: 3, min_spans: 8, max_spans: 20, failure_rate: 0.1, seed: 42 })
const canStart = computed(() => !!task.value && !starting.value && (!bind.value || agents.value.length > 0))

async function openTask(id: string) {
  taskId.value = id
  runError.value = validation.value = ''
  await taskRequest.load(async signal => (await api.task(id, signal)).data)
}

async function createTask() {
  if (creating.value || !title.value.trim() || !scenario.value.trim()) return
  const input = {
    title: title.value.trim(),
    description: description.value.trim() || null,
    scenario_type: scenario.value.trim(),
  }
  const created = await createRequest.load(async signal => (await api.createTask(input, signal)).data)
  if (!created) return
  taskId.value = created.task_id
  taskRequest.cancel()
  task.value = created
  taskError.value = runError.value = validation.value = ''
  showForm.value = false
  title.value = description.value = ''
  scenario.value = 'GENERAL'
  void load(1)
}

function toggleBinding() {
  if (bind.value) void active.load(1)
  else {
    active.cancel()
    agents.value = []
  }
}

function isSelected(agent: Agent) {
  return agents.value.some(item => item.agent_id === agent.agent_id)
}

function toggleAgent(agent: Agent) {
  if (isSelected(agent)) {
    agents.value = agents.value.filter(item => item.agent_id !== agent.agent_id)
  } else if (agents.value.length < 3) {
    agents.value.push(agent)
  }
}

async function startRun() {
  if (!canStart.value) return
  validation.value = ''
  if (config.min_spans > config.max_spans) {
    validation.value = '最少 Span 数不能大于最多 Span 数'
    return
  }
  if (!Number.isSafeInteger(config.seed)) {
    validation.value = '随机种子必须是安全整数'
    return
  }
  const payload: SimulationConfig = {
    ...config,
    ...(bind.value ? { agent_ids: agents.value.map(agent => agent.agent_id), agent_count: agents.value.length } : {}),
  }
  const id = taskId.value
  const accepted = await runRequest.load(async signal => (await api.startRun(id, payload, signal)).data)
  if (accepted) {
    localStorage.setItem('last-run-id', accepted.run_id)
    location.hash = traceHref(accepted.run_id)
  }
}

onMounted(() => void load())
</script>

<template>
  <header class="page-heading">
    <p class="eyebrow">TASKS</p>
    <h1>任务管理</h1>
    <p>查看已有任务，用同一个 Task 多次启动模拟 Run。</p>
  </header>
  <section class="card" aria-labelledby="tasks-list">
    <div class="section-heading">
      <h2 id="tasks-list">任务列表</h2>
      <button type="button" :disabled="creating || starting" @click="showForm = !showForm">{{ showForm ? '收起表单' : '新建任务' }}</button>
    </div>
    <form v-if="showForm" class="form-grid subpanel" @submit.prevent="createTask">
      <label>任务名称 <input v-model="title" maxlength="200" required :disabled="creating" /></label>
      <label>场景类型 <input v-model="scenario" maxlength="50" required :disabled="creating" /></label>
      <label class="wide">任务描述 <textarea v-model="description" rows="2" :disabled="creating" /></label>
      <button :disabled="creating || !title.trim() || !scenario.trim()">{{ creating ? '正在创建…' : '创建任务' }}</button>
      <p v-if="createError" role="alert" class="error wide">{{ createError }}</p>
    </form>
    <LoadState :loading="loading" :error="error" :empty="!items.length" empty-text="暂无任务，可以先新建一个任务。" @retry="load()">
      <div class="table-wrap">
        <table>
          <thead><tr><th>任务名称</th><th>场景</th><th>创建时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="item in items" :key="item.task_id">
              <td>{{ item.title }}</td><td>{{ item.scenario_type }}</td><td>{{ time(item.created_at) }}</td>
              <td><button type="button" class="link-button" :disabled="starting || creating" @click="openTask(item.task_id)">查看 {{ item.title }}</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </LoadState>
    <PageNav v-if="meta" :meta="meta" label="任务分页" @change="load" />
  </section>

  <section v-if="taskId" class="card" aria-labelledby="task-details">
    <h2 id="task-details">任务详情</h2>
    <LoadState :loading="loadingTask" :error="taskError" @retry="openTask(taskId)">
      <template v-if="task">
        <h3>{{ task.title }}</h3>
        <dl>
          <dt>Task ID</dt><dd>{{ task.task_id }}</dd>
          <dt>场景类型</dt><dd>{{ task.scenario_type }}</dd>
          <dt>描述</dt><dd>{{ task.description ?? '—' }}</dd>
          <dt>创建时间</dt><dd>{{ time(task.created_at) }}</dd>
        </dl>
        <p><a :href="`#/runs?task=${encodeURIComponent(task.task_id)}`">查看该任务的运行历史</a></p>
        <form class="subpanel" @submit.prevent="startRun">
          <h3>启动模拟 Run</h3>
          <fieldset :disabled="starting">
            <legend>研究场景参数</legend>
            <label class="check"><input v-model="bind" type="checkbox" @change="toggleBinding" /> 绑定已启用的 Agent</label>
            <template v-if="bind">
              <p class="muted">按研究、分析、审阅的顺序选择 1–3 个 Agent。</p>
              <ol v-if="agents.length" aria-label="已绑定 Agent">
                <li v-for="agent in agents" :key="agent.agent_id">
                  {{ agent.name }} <button type="button" class="link-button" @click="toggleAgent(agent)">移除 {{ agent.name }}</button>
                </li>
              </ol>
              <LoadState :loading="active.loading.value" :error="active.error.value" @retry="active.load()">
                <p v-if="!active.items.value.length">暂无可用 Agent。<a href="#/agents">去创建或启用 Agent</a>，也可以取消绑定。</p>
                <label v-for="agent in active.items.value" :key="agent.agent_id" class="check">
                  <input type="checkbox" :checked="isSelected(agent)" :disabled="!isSelected(agent) && agents.length >= 3" @change="toggleAgent(agent)" />
                  {{ agent.name }} · {{ agent.role }}
                </label>
              </LoadState>
              <PageNav v-if="active.meta.value" :meta="active.meta.value" label="可用 Agent 分页" @change="active.load" />
            </template>
            <div class="form-grid">
              <label v-if="!bind">Agent 数量 <input v-model.number="config.agent_count" type="number" min="1" max="3" step="1" required /></label>
              <label>最少 Span 数 <input v-model.number="config.min_spans" type="number" min="1" max="500" step="1" required /></label>
              <label>最多 Span 数 <input v-model.number="config.max_spans" type="number" min="1" max="500" step="1" required /></label>
              <label>失败率（0–1） <input v-model.number="config.failure_rate" type="number" min="0" max="1" step="any" required /></label>
              <label>随机种子 <input v-model.number="config.seed" type="number" step="1" required /></label>
            </div>
          </fieldset>
          <button :disabled="!canStart || creating">{{ starting ? '等待服务接受…' : '启动模拟 Run' }}</button>
          <p v-if="validation || runError" role="alert" class="error">{{ validation || runError }}</p>
        </form>
      </template>
    </LoadState>
  </section>
</template>
