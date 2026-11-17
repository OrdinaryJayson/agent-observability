<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import LoadState from '../components/LoadState.vue'
import { errorMessage, useRequest } from '../composables/requests'
import { count, ms, time } from '../utils/format'
import { v2 } from './api'
import CursorNav from './CursorNav.vue'
import ExperimentSweep from './ExperimentSweep.vue'
import JsonDetails from './JsonDetails.vue'
import PlanTree from './PlanTree.vue'
import { link, useCursor, useSubmission } from './state'
import { cases, type CaseCode, type Experiment, type ExperimentStart, type Sample } from './types'

const props = defineProps<{ experimentId?: string }>()
const list = useCursor(v2.experiments)
const datasets = useCursor(v2.datasets)
const aggregate = useRequest<Awaited<ReturnType<typeof v2.aggregate>>>()
const experiment = useRequest<Experiment>()
const trials = useCursor((cursor, signal) => v2.trials(props.experimentId!, cursor, signal))
const samples = useCursor((cursor, signal) => v2.samples(props.experimentId!, trialId.value, cursor, signal))
const action = useRequest<unknown>()
const submission = useSubmission<ExperimentStart>('experiment')
const trialId = ref('')
const selected = ref<Sample | null>(null)
const plan = ref<'tree' | 'json'>('tree')
const pollError = ref('')
const cancelNotice = ref('')
const datasetId = ref('')
const code = ref<CaseCode>('INDEX_SELECTIVITY')
const seed = ref(42)
const repetitions = ref<15 | 30>(15)
const query = ref('TRACE')
const selectivity = ref(0.01)
const rank = ref(10000)
const windowDays = ref(30)
const schedule = ref('WRITE_SKEW')
const claimers = ref(4)
const current = experiment.data
const busy = computed(() => action.loading.value)
const isActive = computed(() => current.value?.status === 'QUEUED' || current.value?.status === 'RUNNING')
const max = computed(() => Math.max(0, ...trials.items.value.flatMap(trial => [trial.summary.median_ms ?? 0, trial.summary.p95_ms ?? 0])))
const isMechanism = computed(() => ['MVCC_ISOLATION', 'QUEUE_CONTENTION'].includes(current.value?.case_code ?? ''))
const measured = computed(() => samples.items.value.filter(row => !row.is_warmup))
const sampleMaximum = computed(() => Math.max(0, ...measured.value.map(row =>
  typeof row.metrics.execution_ms === 'number' ? row.metrics.execution_ms : 0)))
const formError = ref('')
let controller: AbortController | undefined
let timer: ReturnType<typeof setTimeout> | undefined

function parameters(): ExperimentStart['parameters'] {
  switch (code.value) {
    case 'INDEX_SELECTIVITY': return { query: query.value, selectivity: selectivity.value }
    case 'JSONB_GIN': return { selectivity: selectivity.value }
    case 'PAGINATION': return { rank: rank.value, limit: 50 }
    case 'AGGREGATION': return { window_days: windowDays.value }
    case 'MVCC_ISOLATION': return { schedule: schedule.value }
    case 'QUEUE_CONTENTION': return { claimers: claimers.value, jobs: 1000 }
  }
}

async function submit() {
  if (busy.value) return
  formError.value = ''
  const pending = submission.attempt.value
  if (!pending && !datasetId.value) { formError.value = '请选择 READY 数据集。'; return }
  const attempt = pending ?? submission.get({
    dataset_id: datasetId.value, case_code: code.value, parameters: parameters(), seed: seed.value, warmups: 3, repetitions: repetitions.value,
  })
  const result = await action.load(async signal => {
    try {
      const created = await v2.startExperiment(attempt.payload, attempt.key, signal)
      submission.clear()
      return created
    } catch (cause) {
      submission.reject(cause)
      throw cause
    }
  }) as Experiment | undefined
  if (result) location.hash = link('experiments', { id: result.experiment_id })
}

async function refreshResult() {
  controller?.abort()
  clearTimeout(timer)
  pollError.value = ''
  if (!props.experimentId) return
  const id = props.experimentId
  const signal = (controller = new AbortController()).signal
  const initial = await experiment.load(() => v2.experiment(id, signal))
  if (!initial || signal.aborted) return
  void trials.reset()
  let delay = 500
  async function poll() {
    try {
      const next = await v2.experiment(id, signal)
      if (signal.aborted) return
      const updated = next.sample_count !== current.value?.sample_count || next.trial_count !== current.value?.trial_count
      current.value = next
      if (updated || !isActive.value) {
        void trials.load()
        if (trialId.value) void samples.load()
      }
      if (isActive.value) {
        delay = Math.min(delay * 2, 2000)
        timer = setTimeout(poll, delay)
      }
    } catch (cause) {
      if (!signal.aborted) pollError.value = errorMessage(cause)
    }
  }
  if (isActive.value) timer = setTimeout(poll, delay)
}
async function cancel() {
  if (busy.value || !props.experimentId) return
  const result = await action.load(async signal => { await v2.cancelExperiment(props.experimentId!, signal); return true })
  if (result) { cancelNotice.value = '取消请求已提交，等待实验执行器更新状态。'; void refreshResult() }
}
function chooseTrial(id: string) { trialId.value = id; selected.value = null; void samples.reset() }
async function download(format: 'json' | 'csv') {
  if (busy.value || !props.experimentId) return
  const id = props.experimentId
  await action.load(async signal => {
    const blob = await v2.export(id, format, signal)
    signal.throwIfAborted()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'experiment-' + id + '.' + format
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  })
}
onMounted(() => { void list.load(); void datasets.load(); void aggregate.load(v2.aggregate); void refreshResult() })
onBeforeUnmount(() => { controller?.abort(); clearTimeout(timer) })
</script>

<template>
  <header class="page-heading"><h1>数据库实验</h1><p>以登记数据集运行固定实验，查看方案、实际测量和正确性证据。</p></header>
  <section class="card">
    <h2>新建实验</h2>
    <p>查询实验比较中位数、P95 和配对差异的置信区间。事务机制实验以可见性与不变量为主。</p>
    <form @submit.prevent="submit">
      <fieldset :disabled="busy || !!submission.attempt.value">
        <LoadState :loading="datasets.loading.value" :error="datasets.error.value" @retry="datasets.reset()">
          <label for="experiment-dataset">数据集</label>
            <select id="experiment-dataset" v-model="datasetId" required><option value="">选择 READY 数据集</option>
              <option v-for="item in datasets.items.value.filter(dataset => dataset.state === 'READY')" :key="item.dataset_id" :value="item.dataset_id">
                {{ item.name }} · {{ item.purpose }} · {{ item.actual_counts.spans ?? '—' }} Span
              </option>
            </select>
          <p v-if="!datasets.items.value.some(item => item.state === 'READY')" class="muted">此页暂无就绪数据集。<a href="#/data">查看数据集登记</a></p>
        </LoadState>
        <CursorNav :back="!!datasets.trail.value.length" :forward="!!datasets.nextCursor.value" :loading="datasets.loading.value" @previous="datasets.previous" @next="datasets.next" />
        <div class="form-grid v2-toolbar">
          <label>案例 <select v-model="code" aria-label="案例"><option v-for="(label, value) in cases" :key="value" :value="value">{{ label }}</option></select></label>
          <label v-if="code === 'INDEX_SELECTIVITY'">查询类型 <select v-model="query"><option>TRACE</option><option>ERROR</option></select></label>
          <label v-if="code === 'INDEX_SELECTIVITY' || code === 'JSONB_GIN'">选择率 <select v-model.number="selectivity"><option v-for="n in [.001,.01,.1,.5]" :key="n" :value="n">{{ n }}</option></select></label>
          <label v-if="code === 'PAGINATION'">目标位置 <select v-model.number="rank"><option v-for="n in [0,10000,100000]" :key="n" :value="n">{{ n }}</option></select></label>
          <label v-if="code === 'AGGREGATION'">窗口天数 <select v-model.number="windowDays"><option v-for="n in [1,7,30,90]" :key="n" :value="n">{{ n }}</option></select></label>
          <label v-if="code === 'MVCC_ISOLATION'">事务交错 <select v-model="schedule"><option>NON_REPEATABLE_READ</option><option>WRITE_SKEW</option></select></label>
          <label v-if="code === 'QUEUE_CONTENTION'">并发领取者 <select v-model.number="claimers"><option v-for="n in [1,2,4,8]" :key="n" :value="n">{{ n }}</option></select></label>
          <label>随机种子 <input v-model.number="seed" type="number" min="-2147483648" max="2147483647" required /></label>
          <label>测量轮数 <select v-model.number="repetitions"><option :value="15">15</option><option :value="30">30</option></select></label>
        </div>
      </fieldset>
      <div class="actions"><button :disabled="busy || !submission.attempt.value && !datasetId">{{ submission.attempt.value ? '重试同一次实验' : '提交实验' }}</button>
        <button v-if="submission.attempt.value" class="secondary" type="button" :disabled="busy" @click="submission.clear()">放弃本次提交记录</button>
      </div>
      <p v-if="submission.attempt.value && !busy">上次响应未知。保留原参数和请求键重试。</p>
    </form>
    <p v-if="formError || action.error.value" class="notice error" role="alert">{{ formError || action.error.value }}</p>
  </section>

  <section v-if="experimentId" class="card">
    <LoadState :loading="experiment.loading.value" :error="experiment.error.value" @retry="refreshResult">
      <template v-if="current">
        <div class="section-heading"><h2>{{ cases[current.case_code] }}</h2><span :class="['badge', current.status]">{{ current.status }}</span></div>
        <p>{{ current.phase ?? '等待阶段更新' }} · {{ current.progress === null ? '进度待定' : Math.round(current.progress * 100) + '%' }} · {{ current.sample_count }} 个已保存样本</p>
        <p>数据集 <a :href="link('data', { dataset: current.dataset_id })">{{ current.dataset_id }}</a> · 协议 {{ current.protocol_version }} · 代码 {{ current.code_revision ?? '—' }}</p>
        <JsonDetails label="环境与配置" :value="{ environment: current.environment, config: current.config }" />
        <p v-if="current.error_code" class="error" role="alert">{{ current.error_code }}</p>
        <p v-if="pollError" class="error" role="alert">{{ pollError }} <button class="secondary" @click="refreshResult">恢复查询</button></p>
        <p v-if="cancelNotice" role="status">{{ cancelNotice }}</p>
        <button v-if="isActive" class="secondary" :disabled="busy || !!current.cancel_requested_at" @click="cancel">取消实验</button>
        <div v-else class="actions v2-toolbar"><button class="secondary" :disabled="busy" @click="download('json')">导出 JSON</button>
          <button class="secondary" :disabled="busy" @click="download('csv')">导出 CSV</button></div>
        <h3>方案结果</h3>
        <p v-if="isMechanism">请根据样本的正确性检查和机制证据评估结果。</p>
        <p v-else>耗时单位为 ms，预热不计入汇总。标记为失败的样本仍可查看。</p>
        <LoadState :loading="trials.loading.value" :error="trials.error.value" :empty="!trials.items.value.length" @retry="trials.reset()">
          <div v-if="!isMechanism && max > 0" class="v2-trial-chart" aria-label="各方案 P95 与中位数">
            <div v-for="trial in trials.items.value" :key="trial.trial_id">
              <span>{{ trial.variant }}</span>
              <span class="v2-bar" :title="'中位数 ' + ms(trial.summary.median_ms)" :style="{ width: (100 * (trial.summary.median_ms ?? 0) / max) + '%' }"></span>
              <span class="v2-bar v2-bar-secondary" :title="'P95 ' + ms(trial.summary.p95_ms)" :style="{ width: (100 * (trial.summary.p95_ms ?? 0) / max) + '%' }"></span>
            </div>
          </div>
          <div class="table-wrap v2-scroll"><table><thead><tr><th>方案</th><th>参数</th><th>样本 / 失败</th><th>中位数 / P95 / IQR</th><th>配对差异与 95% CI</th></tr></thead><tbody>
            <tr v-for="trial in trials.items.value" :key="trial.trial_id">
              <th><button class="link-button" @click="chooseTrial(trial.trial_id)">{{ trial.variant }}</button></th><td><JsonDetails label="参数" :value="trial.parameters" /></td>
              <td>{{ trial.summary.n }} / {{ trial.summary.failed_samples }}</td><td>{{ ms(trial.summary.median_ms) }} / {{ ms(trial.summary.p95_ms) }} / {{ ms(trial.summary.iqr_ms) }}</td>
              <td>{{ ms(trial.summary.paired_difference_ms) }} <small>{{ trial.summary.bootstrap_ci95_ms?.map(ms).join(' 至 ') ?? '—' }}</small></td>
            </tr>
          </tbody></table></div>
        </LoadState>
        <CursorNav :back="!!trials.trail.value.length" :forward="!!trials.nextCursor.value" :loading="trials.loading.value" @previous="trials.previous" @next="trials.next" />
        <template v-if="trialId">
          <h3>原始样本</h3>
          <LoadState :loading="samples.loading.value" :error="samples.error.value" :empty="!samples.items.value.length" @retry="samples.reset()">
            <figure v-if="!isMechanism && sampleMaximum > 0" class="v2-samples">
              <figcaption>当前页 · 每轮执行耗时（ms）</figcaption>
              <div class="chart-scroll">
                <ol class="trend-chart" aria-label="每轮测量结果">
                  <li v-for="row in measured" :key="row.repetition">
                    <div class="chart-bars">
                      <span v-if="typeof row.metrics.execution_ms === 'number'" :class="row.correctness.passed ? 'success' : 'failed'"
                        :style="{ height: (row.metrics.execution_ms / sampleMaximum * 100) + '%' }"
                        :title="'轮次 ' + row.repetition + ' · ' + ms(row.metrics.execution_ms)"></span>
                    </div>
                    <small>{{ row.repetition }}</small>
                  </li>
                </ol>
              </div>
            </figure>
            <div class="table-wrap v2-scroll"><table><thead><tr><th>轮次</th><th>类型</th><th>执行 / 客户端</th><th>索引空间与插入耗时</th><th>正确性</th></tr></thead><tbody>
              <tr v-for="row in samples.items.value" :key="row.repetition">
                <td><button class="link-button" @click="selected = row">样本 {{ row.repetition }}</button></td><td>{{ row.is_warmup ? '预热' : '测量' }}</td>
                <td>{{ ms(typeof row.metrics.execution_ms === 'number' ? row.metrics.execution_ms : null) }} / {{ ms(typeof row.metrics.client_ms === 'number' ? row.metrics.client_ms : null) }}</td>
                <td>{{ count(typeof row.metrics.index_bytes === 'number' ? row.metrics.index_bytes : null) }} B / {{ ms(typeof row.metrics.insert_ms === 'number' ? row.metrics.insert_ms : null) }}</td>
                <td>{{ row.correctness.passed ? '通过' : '失败' }}</td>
              </tr>
            </tbody></table></div>
          </LoadState>
          <CursorNav :back="!!samples.trail.value.length" :forward="!!samples.nextCursor.value" :loading="samples.loading.value" @previous="samples.previous" @next="samples.next" />
        </template>
        <div v-if="selected" class="subpanel">
          <h3>样本 {{ selected.repetition }} · {{ time(selected.measured_at) }}</h3>
          <JsonDetails label="全部指标与正确性证据" :value="{ metrics: selected.metrics, correctness: selected.correctness }" />
          <div v-if="selected.plan" class="actions v2-toolbar">
            <button class="secondary" :aria-pressed="plan === 'tree'" @click="plan = 'tree'">计划树</button>
            <button class="secondary" :aria-pressed="plan === 'json'" @click="plan = 'json'">计划 JSON</button>
          </div>
          <PlanTree v-if="selected.plan && plan === 'tree'" :plan="selected.plan" />
          <pre v-else-if="selected.plan">{{ JSON.stringify(selected.plan, null, 2) }}</pre><p v-else>此样本无执行计划。</p>
        </div>
      </template>
    </LoadState>
  </section>

  <section class="card"><h2>实验历史</h2>
    <LoadState :loading="list.loading.value" :error="list.error.value" :empty="!list.items.value.length" @retry="list.reset()">
      <div class="table-wrap"><table><thead><tr><th>实验</th><th>状态</th><th>提交时间</th><th>样本数</th></tr></thead><tbody>
        <tr v-for="row in list.items.value" :key="row.experiment_id"><td><a :href="link('experiments', { id: row.experiment_id })">{{ cases[row.case_code] }}</a></td>
          <td>{{ row.status }}</td><td>{{ time(row.created_at) }}</td><td>{{ row.sample_count }}</td></tr>
      </tbody></table></div>
    </LoadState>
    <CursorNav :back="!!list.trail.value.length" :forward="!!list.nextCursor.value" :loading="list.loading.value" @previous="list.previous" @next="list.next" />
    <ExperimentSweep :experiments="list.items.value" />
    <p v-if="aggregate.data.value">日聚合水位 {{ aggregate.data.value.watermark_max_seq }} · {{ time(aggregate.data.value.snapshot_at) }} · {{ aggregate.data.value.stale ? '待刷新' : '已同步' }}</p>
  </section>
</template>
