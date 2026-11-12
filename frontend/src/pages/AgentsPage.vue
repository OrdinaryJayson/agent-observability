<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api/client'
import LoadState from '../components/LoadState.vue'
import PageNav from '../components/PageNav.vue'
import { usePage, useRequest } from '../composables/requests'
import { agentStatuses, type Agent, type AgentInput, type AgentPatch } from '../types'
import { time } from '../utils/format'

const status = ref<Agent['status'] | ''>('')
const { items, meta, loading, error, load } = usePage((page, signal) => api.agents(page, status.value, signal))
const detail = useRequest<Agent>()
const write = useRequest<Agent>()
const { loading: saving, error: saveError } = write
const { data: selected, loading: viewing, error: viewError } = detail
const mode = ref<'create' | 'view' | 'edit' | null>(null)
const selectedId = ref('')
const form = reactive({ name: '', role: '', provider: '', model_name: '' })
const saved = ref('')

const input = computed<AgentInput>(() => ({
  name: form.name.trim(),
  role: form.role.trim(),
  provider: form.provider.trim() || null,
  model_name: form.model_name.trim() || null,
}))

const patch = computed<AgentPatch>(() => {
  const current = selected.value
  if (!current) return {}
  const changed: AgentPatch = {}
  for (const field of ['name', 'role', 'provider', 'model_name'] as const) {
    if (form[field] !== (current[field] ?? '') && input.value[field] !== current[field]) {
      Object.assign(changed, { [field]: input.value[field] })
    }
  }
  return changed
})

function create() {
  detail.cancel()
  selectedId.value = ''
  Object.assign(form, { name: '', role: '', provider: '', model_name: '' })
  saveError.value = saved.value = ''
  mode.value = 'create'
}

async function view(id: string) {
  mode.value = 'view'
  selectedId.value = id
  saveError.value = saved.value = ''
  await detail.load(async signal => (await api.agent(id, signal)).data)
}

function edit(agent: Agent) {
  Object.assign(form, {
    name: agent.name,
    role: agent.role,
    provider: agent.provider ?? '',
    model_name: agent.model_name ?? '',
  })
  saveError.value = saved.value = ''
  mode.value = 'edit'
}

async function persist(fetchAgent: (signal: AbortSignal) => Promise<Agent>, message: string, firstPage = false) {
  if (saving.value) return
  saved.value = ''
  const agent = await write.load(fetchAgent)
  if (!agent) return
  selected.value = agent
  selectedId.value = agent.agent_id
  mode.value = 'view'
  saved.value = message
  await load(firstPage ? 1 : undefined)
}

function save() {
  if (!input.value.name || !input.value.role) return
  if (mode.value === 'create') {
    const payload = input.value
    return persist(async signal => (await api.createAgent(payload, signal)).data, '已创建 Agent。', true)
  }
  const id = selectedId.value
  const changes = patch.value
  if (!Object.keys(changes).length) return
  return persist(async signal => (await api.updateAgent(id, changes, signal)).data, '已保存修改。')
}

function toggle(agent: Agent) {
  const next = agent.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE'
  return persist(
    async signal => (await api.updateAgent(agent.agent_id, { status: next }, signal)).data,
    next === 'ACTIVE' ? '已启用 Agent。' : '已停用 Agent。',
  )
}

function close() {
  detail.cancel()
  mode.value = null
  saveError.value = saved.value = ''
}

function cancelEdit() {
  saveError.value = ''
  mode.value = 'view'
}

onMounted(() => void load())
</script>

<template>
  <header class="page-heading">
    <p class="eyebrow">AGENTS</p>
    <h1>Agent 管理</h1>
    <p>维护参与模拟运行的 Agent、角色和模型信息。</p>
  </header>

  <section class="card" aria-labelledby="agents-list">
    <div class="section-heading">
      <h2 id="agents-list">Agent 列表</h2>
      <button type="button" :disabled="saving" @click="create">新建 Agent</button>
    </div>
    <label class="filter-field">
      Agent 状态
      <select v-model="status" @change="load(1)">
        <option value="">全部状态</option>
        <option v-for="value in agentStatuses" :key="value">{{ value }}</option>
      </select>
    </label>
    <LoadState :loading="loading" :error="error" :empty="!items.length" empty-text="没有符合条件的 Agent。" @retry="load()">
      <div class="table-wrap">
        <table>
          <thead><tr><th>名称</th><th>角色</th><th>提供商 / 模型</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="agent in items" :key="agent.agent_id">
              <td>{{ agent.name }}</td><td>{{ agent.role }}</td>
              <td>{{ agent.provider ?? '—' }} / {{ agent.model_name ?? '—' }}</td>
              <td><span :class="['badge', agent.status]">{{ agent.status }}</span></td>
              <td>{{ time(agent.created_at) }}</td>
              <td><button type="button" class="link-button" :disabled="saving" @click="view(agent.agent_id)">查看 {{ agent.name }}</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </LoadState>
    <PageNav v-if="meta" :meta="meta" label="Agent 分页" @change="load" />
  </section>

  <section v-if="mode" class="card" aria-labelledby="agent-details">
    <div class="section-heading">
      <h2 id="agent-details">{{ mode === 'create' ? '新建 Agent' : mode === 'edit' ? '编辑 Agent' : 'Agent 详情' }}</h2>
      <button type="button" class="secondary" :disabled="saving" @click="close">关闭</button>
    </div>
    <form v-if="mode !== 'view'" class="form-grid" @submit.prevent="save">
      <label>Agent 名称 <input v-model="form.name" maxlength="100" required :disabled="saving" /></label>
      <label>角色 <input v-model="form.role" maxlength="50" required :disabled="saving" /></label>
      <label>模型提供商 <input v-model="form.provider" maxlength="80" :disabled="saving" /></label>
      <label>模型名称 <input v-model="form.model_name" maxlength="120" :disabled="saving" /></label>
      <div class="actions wide">
        <button :disabled="saving || !input.name || !input.role || (mode === 'edit' && !Object.keys(patch).length)">
          {{ saving ? '正在保存…' : '保存 Agent' }}
        </button>
        <button v-if="mode === 'edit'" type="button" class="secondary" :disabled="saving" @click="cancelEdit">取消编辑</button>
      </div>
    </form>
    <LoadState v-else :loading="viewing" :error="viewError" @retry="view(selectedId)">
      <template v-if="selected">
        <dl>
          <dt>Agent ID</dt><dd>{{ selected.agent_id }}</dd>
          <dt>名称</dt><dd>{{ selected.name }}</dd>
          <dt>角色</dt><dd>{{ selected.role }}</dd>
          <dt>模型提供商</dt><dd>{{ selected.provider ?? '—' }}</dd>
          <dt>模型名称</dt><dd>{{ selected.model_name ?? '—' }}</dd>
          <dt>状态</dt><dd><span :class="['badge', selected.status]">{{ selected.status }}</span></dd>
          <dt>创建时间</dt><dd>{{ time(selected.created_at) }}</dd>
        </dl>
        <div class="actions">
          <button type="button" class="secondary" :disabled="saving" @click="edit(selected)">编辑 Agent</button>
          <button type="button" :disabled="saving" @click="toggle(selected)">{{ selected.status === 'ACTIVE' ? '停用 Agent' : '启用 Agent' }}</button>
        </div>
      </template>
    </LoadState>
    <p v-if="saveError" role="alert" class="error">{{ saveError }}</p>
    <p v-if="saved" role="status">{{ saved }}</p>
  </section>
</template>
