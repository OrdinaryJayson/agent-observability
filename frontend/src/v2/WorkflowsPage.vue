<script setup lang="ts">
import { computed, onMounted, ref, toRaw, watch } from 'vue'
import LoadState from '../components/LoadState.vue'
import { useRequest } from '../composables/requests'
import { time } from '../utils/format'
import { ApiError, v2 } from './api'
import CursorNav from './CursorNav.vue'
import GraphView from './GraphView.vue'
import JsonDetails from './JsonDetails.vue'
import { canonical, definitionHash, initialDefinition, nodeConfig } from './graph'
import { link, useCursor } from './state'
import { nodeTypes, scenarios, type Definition, type Edge, type Validation, type Version, type Workflow, type WorkflowNode } from './types'

const props = defineProps<{ workflowId?: string }>()
const list = useCursor(v2.workflows)
const selected = ref<Workflow | null>(null)
const draft = ref<Definition>(initialDefinition('RESEARCH_PIPELINE'))
const name = ref('')
const description = ref('')
const template = ref<Definition['scenario']>('RESEARCH_PIPELINE')
const nodeIndex = ref(0)
const graph = ref(true)
const editor = ref(false)
const version = ref<Version | null>(null)
const conflict = ref(false)
const report = ref<Validation | null>(null)
const notice = ref('')
const { loading, error, load } = useRequest<unknown>()
const versions = useCursor((cursor, signal) => v2.versions(selected.value!.workflow_id, cursor, signal))
const nodes = computed(() => draft.value.nodes.map((node, index) => ({ id: String(index), label: node.name, caption: node.type + ' · ' + node.node_key })))
const edges = computed(() => draft.value.edges.flatMap(edge => {
  const source = draft.value.nodes.findIndex(node => node.node_key === edge.source)
  const target = draft.value.nodes.findIndex(node => node.node_key === edge.target)
  return source >= 0 && target >= 0 ? [{ source: String(source), target: String(target), label: edge.route === 'ALWAYS' ? undefined : edge.route }] : []
}))
const activeNode = computed(() => draft.value.nodes[nodeIndex.value])
watch(draft, () => { report.value = null }, { deep: true, flush: 'sync' })
const dirty = computed(() => selected.value && (
  name.value.trim() !== selected.value.name || (description.value.trim() || null) !== selected.value.description
  || canonical(draft.value) !== canonical(selected.value.draft)
))
const definitionDiff = computed(() => version.value ? {
  added_nodes: draft.value.nodes.filter(node => !version.value!.definition.nodes.some(old => old.node_key === node.node_key)).map(node => node.node_key),
  removed_nodes: version.value.definition.nodes.filter(node => !draft.value.nodes.some(next => next.node_key === node.node_key)).map(node => node.node_key),
  updated_nodes: draft.value.nodes.filter(node => version.value!.definition.nodes.some(old => old.node_key === node.node_key && canonical(old) !== canonical(node))).map(node => node.node_key),
  changed_edges: canonical(draft.value.edges) !== canonical(version.value.definition.edges),
  changed_roles: canonical(draft.value.roles) !== canonical(version.value.definition.roles),
  changed_scenario: draft.value.scenario !== version.value.definition.scenario,
} : null)

function setWorkflow(workflow: Workflow) {
  selected.value = workflow
  draft.value = structuredClone(toRaw(workflow.draft))
  name.value = workflow.name
  description.value = workflow.description ?? ''
  nodeIndex.value = 0
  version.value = null
  conflict.value = false
  report.value = null
  editor.value = true
  void versions.reset()
}
async function open(id: string) {
  const workflow = await load(signal => v2.workflow(id, signal))
  if (workflow) setWorkflow(workflow as Workflow)
}
function newDraft() {
  selected.value = version.value = null
  name.value = description.value = notice.value = error.value = ''
  conflict.value = false
  report.value = null
  resetTemplate()
  editor.value = true
}
function resetTemplate() { draft.value = initialDefinition(template.value); nodeIndex.value = 0 }
function addNode() {
  let index = draft.value.nodes.length + 1
  while (draft.value.nodes.some(node => node.node_key === 'step_' + index)) index++
  draft.value.nodes.push({ node_key: 'step_' + index, name: '新步骤', type: 'TOOL', role_key: null, config: nodeConfig('TOOL') })
  nodeIndex.value = draft.value.nodes.length - 1
}
function changeKey(node: WorkflowNode, key: string) {
  const old = node.node_key
  if (draft.value.nodes.some(other => other !== node && other.node_key === key)) {
    notice.value = '节点标识已存在。'
    return
  }
  node.node_key = key
  for (const edge of draft.value.edges) {
    if (edge.source === old) edge.source = key
    if (edge.target === old) edge.target = key
  }
}
function removeNode(index: number) {
  const key = draft.value.nodes[index].node_key
  draft.value.nodes.splice(index, 1)
  draft.value.edges = draft.value.edges.filter(edge => edge.source !== key && edge.target !== key)
  nodeIndex.value = Math.max(0, Math.min(index, draft.value.nodes.length - 1))
}
function addEdge() {
  const [source, target] = draft.value.nodes
  if (source && target) draft.value.edges.push({ source: source.node_key, target: target.node_key, route: 'ALWAYS' })
}
function addRole() {
  let id = draft.value.roles.length + 1
  while (draft.value.roles.some(role => role.role_key === 'role_' + id)) id++
  draft.value.roles.push({ role_key: 'role_' + id, name: '新角色' })
}
function renameRole(index: number, key: string) {
  const role = draft.value.roles[index]
  if (draft.value.roles.some(other => other !== role && other.role_key === key)) {
    notice.value = '角色标识已存在。'
    return
  }
  for (const node of draft.value.nodes) if (node.role_key === role.role_key) node.role_key = key
  role.role_key = key
}
function removeRole(index: number) {
  const [role] = draft.value.roles.splice(index, 1)
  for (const node of draft.value.nodes) if (node.role_key === role.role_key) node.role_key = null
}
function setToken(node: WorkflowNode, key: 'input_tokens' | 'output_tokens', value: string) {
  if (value === '') delete node.config[key]
  else node.config[key] = Number(value)
}

async function revisionRequest<T>(request: (signal: AbortSignal) => Promise<T>, signal: AbortSignal) {
  try { return await request(signal) }
  catch (cause) {
    if (cause instanceof ApiError && cause.status === 412 && !signal.aborted) conflict.value = true
    throw cause
  }
}
async function save() {
  if (loading.value || !name.value.trim()) return
  report.value = null
  const input = { name: name.value.trim(), description: description.value.trim() || null, draft: draft.value }
  const saved = selected.value
  const workflow = await load(signal => revisionRequest(inner => saved
    ? v2.updateWorkflow(saved.workflow_id, saved.revision, input, inner)
    : v2.createWorkflow(input, inner), signal))
  if (workflow) {
    setWorkflow(workflow as Workflow)
    notice.value = '草稿已保存。'
    void list.reset()
  }
}
async function validate() {
  if (!selected.value || loading.value) return
  const id = selected.value.workflow_id
  const result = await load(signal => v2.validate(id, draft.value, signal))
  if (result) report.value = result as Validation
}
async function publish() {
  const workflow = selected.value
  if (!workflow || dirty.value || conflict.value || workflow.archived_at || report.value?.valid === false) return
  const published = await load(async signal => {
    const hash = await definitionHash(workflow.draft)
    return revisionRequest(inner => v2.publish(workflow.workflow_id, workflow.revision, hash, inner), signal)
  })
  if (published) {
    const publishedVersion = published as Version
    notice.value = '版本已发布。'
    await open(workflow.workflow_id)
    version.value = publishedVersion
    void versions.reset()
  }
}
async function toggleArchive() {
  const workflow = selected.value
  if (!workflow || dirty.value || conflict.value) return
  const archived = !workflow.archived_at
  const next = await load(signal => revisionRequest(inner =>
    v2.updateWorkflow(workflow.workflow_id, workflow.revision, { archived }, inner), signal))
  if (next) {
    setWorkflow(next as Workflow)
    notice.value = archived ? '工作流已归档。' : '工作流已恢复。'
    void list.reset()
  }
}
async function loadVersion(id: string) {
  const result = await load(signal => v2.version(id, signal))
  if (result) version.value = result as Version
}
function copyVersion() {
  if (!version.value) return
  const copy = version.value
  newDraft()
  name.value = '工作流副本'
  draft.value = structuredClone(toRaw(copy.definition))
}
function focusIssue(issue: Validation['errors'][number]) {
  const index = draft.value.nodes.findIndex(node => node.node_key === issue.node_key)
  if (index >= 0) {
    nodeIndex.value = index
    document.getElementById('workflow-node-editor')?.focus()
  } else if (issue.edge_index !== null) {
    document.getElementById('workflow-edge-' + issue.edge_index)?.focus()
  }
}
onMounted(() => { void list.load(); if (props.workflowId) void open(props.workflowId) })
</script>

<template>
  <header class="page-heading"><h1>工作流</h1><p>编辑草稿，校验依赖关系并发布不可变版本。</p></header>
  <section class="card">
    <div class="section-heading"><h2>工作流列表</h2><button :disabled="loading" @click="newDraft">新建工作流</button></div>
    <LoadState :loading="list.loading.value" :error="list.error.value" :empty="!list.items.value.length" @retry="list.reset()">
      <div class="table-wrap"><table><thead><tr><th>名称</th><th>修订号</th><th>修改时间</th></tr></thead>
        <tbody><tr v-for="workflow in list.items.value" :key="workflow.workflow_id">
          <td><a :href="link('workflows', { id: workflow.workflow_id })">{{ workflow.name }}</a><small v-if="workflow.archived_at">已归档</small></td>
          <td>{{ workflow.revision }}</td><td>{{ time(workflow.updated_at) }}</td>
        </tr></tbody></table></div>
    </LoadState>
    <CursorNav :back="!!list.trail.value.length" :forward="!!list.nextCursor.value" :loading="list.loading.value" @previous="list.previous" @next="list.next" />
  </section>

  <p v-if="loading" role="status">正在处理工作流…</p>
  <div v-if="error" class="notice error" role="alert">
    {{ error }}
    <p v-if="conflict">草稿已被其他人更新。本地编辑仍可查看，请核对服务端修订后再保存。</p>
    <button v-if="props.workflowId || selected" type="button" class="secondary" @click="open(selected?.workflow_id || props.workflowId!)">载入服务器草稿</button>
  </div>
  <p v-if="notice" role="status">{{ notice }}</p>

  <section v-if="editor" class="card">
    <div class="section-heading"><h2>编辑草稿</h2><span v-if="selected">修订 {{ selected.revision }}{{ dirty ? ' · 有未保存修改' : '' }}</span></div>
    <form @submit.prevent="save">
      <fieldset :disabled="loading">
        <div class="form-grid">
          <label>工作流名称 <input v-model="name" maxlength="100" required /></label>
          <label>描述 <input v-model="description" /></label>
          <label>场景 <select v-model="draft.scenario"><option v-for="scenario in scenarios" :key="scenario">{{ scenario }}</option></select></label>
        </div>
        <div class="actions v2-toolbar" v-if="!selected">
          <label>模板 <select v-model="template"><option v-for="scenario in scenarios" :key="scenario">{{ scenario }}</option></select></label>
          <button type="button" class="secondary" @click="resetTemplate">加载模板</button>
        </div>
        <div class="actions v2-toolbar">
          <button type="button" class="secondary" :aria-pressed="graph" @click="graph = true">图视图</button>
          <button type="button" class="secondary" :aria-pressed="!graph" @click="graph = false">表视图</button>
          <button type="button" :disabled="draft.nodes.length >= 50" @click="addNode">添加节点</button>
        </div>
        <GraphView v-if="graph" :nodes="nodes" :edges="edges" :selected="String(nodeIndex)" @select="nodeIndex = Number($event)" />
        <div v-else class="table-wrap v2-scroll"><table><thead><tr><th>标识</th><th>类型</th><th>名称</th><th>角色</th></tr></thead>
          <tbody><tr v-for="(node, index) in draft.nodes" :key="index">
            <td><button type="button" class="link-button" @click="nodeIndex = index">{{ node.node_key }}</button></td><td>{{ node.type }}</td><td>{{ node.name }}</td><td>{{ node.role_key ?? '—' }}</td>
          </tr></tbody></table></div>
        <section v-if="activeNode" id="workflow-node-editor" tabindex="-1" class="subpanel">
          <h3>节点配置</h3>
          <div class="form-grid">
            <label>节点标识 <input :value="activeNode.node_key" required pattern="(?!sys_)[a-z][a-z0-9_]{0,49}" @change="changeKey(activeNode, ($event.target as HTMLInputElement).value)" /></label>
            <label>节点名称 <input v-model="activeNode.name" required maxlength="100" /></label>
            <label>类型 <select v-model="activeNode.type" @change="activeNode.config = nodeConfig(activeNode.type)"><option v-for="type in nodeTypes" :key="type">{{ type }}</option></select></label>
            <label>角色 <select v-model="activeNode.role_key"><option :value="null">无归属</option><option v-for="role in draft.roles" :key="role.role_key" :value="role.role_key">{{ role.name }}</option></select></label>
            <template v-if="activeNode.type === 'CONDITION'">
              <label>条件结果 <select v-model="activeNode.config.result"><option>PASS</option><option>FAIL</option><option>SEEDED</option></select></label>
            </template>
            <template v-else-if="['LLM', 'TOOL', 'RETRIEVAL'].includes(activeNode.type)">
              <label>耗时（ms） <input v-model.number="activeNode.config.duration_ms" type="number" min="100" max="1500" required /></label>
              <label>失败概率 <input v-model.number="activeNode.config.failure_probability" type="number" min="0" max="1" step="any" required /></label>
              <label>重试上限 <input v-model.number="activeNode.config.max_retries" type="number" min="0" max="2" required /></label>
              <template v-if="activeNode.type === 'LLM'">
                <label>输入 Token <input :value="activeNode.config.input_tokens" type="number" min="0" max="100000" placeholder="50" @change="setToken(activeNode, 'input_tokens', ($event.target as HTMLInputElement).value)" /></label>
                <label>输出 Token <input :value="activeNode.config.output_tokens" type="number" min="0" max="100000" placeholder="20" @change="setToken(activeNode, 'output_tokens', ($event.target as HTMLInputElement).value)" /></label>
              </template>
            </template>
          </div>
          <button type="button" class="secondary" :disabled="draft.nodes.length <= 2" @click="removeNode(nodeIndex)">删除当前节点</button>
        </section>
        <details open class="subpanel">
          <summary>依赖连线（{{ draft.edges.length }}）</summary>
          <div v-for="(edge, index) in draft.edges" :key="index" class="form-grid v2-edit-row">
            <label>起点 <select :id="'workflow-edge-' + index" v-model="edge.source"><option v-for="node in draft.nodes" :key="node.node_key" :value="node.node_key">{{ node.node_key }}</option></select></label>
            <label>终点 <select v-model="edge.target"><option v-for="node in draft.nodes" :key="node.node_key" :value="node.node_key">{{ node.node_key }}</option></select></label>
            <label>路由 <select v-model="edge.route"><option v-for="route in (['ALWAYS', 'PASS', 'FAIL'] as Edge['route'][])" :key="route">{{ route }}</option></select></label>
            <button type="button" class="secondary" @click="draft.edges.splice(index, 1)">删除连线 {{ index + 1 }}</button>
          </div>
          <button type="button" class="secondary" :disabled="draft.edges.length >= 100" @click="addEdge">添加连线</button>
        </details>
        <details class="subpanel">
          <summary>角色（{{ draft.roles.length }}）</summary>
          <div v-for="(role, index) in draft.roles" :key="index" class="form-grid v2-edit-row">
            <label>角色标识 <input :value="role.role_key" required pattern="(?!sys_)[a-z][a-z0-9_]{0,49}" @change="renameRole(index, ($event.target as HTMLInputElement).value)" /></label>
            <label>角色名称 <input v-model="role.name" required maxlength="100" /></label>
            <button type="button" class="secondary" @click="removeRole(index)">删除角色 {{ index + 1 }}</button>
          </div>
          <button type="button" class="secondary" :disabled="draft.roles.length >= 8" @click="addRole">添加角色</button>
        </details>
        <div class="actions">
          <button :disabled="conflict">保存草稿</button>
          <button type="button" class="secondary" :disabled="!selected" @click="validate">校验草稿</button>
          <button type="button" class="secondary" :disabled="!selected || !!dirty || conflict || !!selected.archived_at || report?.valid === false" @click="publish">发布已保存草稿</button>
          <button v-if="selected" type="button" class="secondary" :disabled="!!dirty || conflict" @click="toggleArchive">{{ selected.archived_at ? '恢复工作流' : '归档工作流' }}</button>
        </div>
      </fieldset>
    </form>
    <div v-if="report" class="subpanel" aria-live="polite">
      <p v-if="report.valid">工作流语义校验通过。</p>
      <ul v-else><li v-for="(issue, index) in report.errors" :key="index">
        <button type="button" class="link-button" @click="focusIssue(issue)">{{ issue.node_key ?? issue.path }} · {{ issue.code }} · {{ issue.message }}</button>
      </li></ul>
    </div>
  </section>

  <section v-if="selected" class="card">
    <h2>发布版本</h2>
    <LoadState :loading="versions.loading.value" :error="versions.error.value" :empty="!versions.items.value.length" @retry="versions.reset()">
      <ul><li v-for="entry in versions.items.value" :key="entry.version_id">
        <button type="button" class="link-button" :disabled="loading" @click="loadVersion(entry.version_id)">查看版本 {{ entry.version_no }}</button> · {{ time(entry.created_at) }}
      </li></ul>
    </LoadState>
    <CursorNav :back="!!versions.trail.value.length" :forward="!!versions.nextCursor.value" :loading="versions.loading.value" @previous="versions.previous" @next="versions.next" />
    <template v-if="version">
      <h3>版本 {{ version.version_no }} · 只读</h3>
      <p><code>{{ version.definition_hash }}</code></p>
      <JsonDetails label="工作流定义" :value="version.definition" />
      <JsonDetails label="与当前草稿的结构差异" :value="definitionDiff" />
      <div class="actions v2-toolbar">
        <button class="secondary" type="button" @click="copyVersion">复制版本为新草稿</button>
        <a :href="link('run-center', { version: version.version_id })">以此版本启动运行</a>
      </div>
    </template>
  </section>
</template>
