<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import LoadState from '../components/LoadState.vue'
import TimeFilter from '../components/TimeFilter.vue'
import { useRequest } from '../composables/requests'
import OverviewPage from '../pages/OverviewPage.vue'
import type { TimeWindow } from '../types'
import { count, ms, percent, time } from '../utils/format'
import { ApiError, v2 } from './api'
import JsonDetails from './JsonDetails.vue'
import { link, traceLink } from './state'
import type { ClockMode, JsonObject, OverviewV2 } from './types'

const request = useRequest<OverviewV2>()
const series = useRequest<JsonObject[]>()
const demos = useRequest<OverviewV2['recent_runs'][number] | null>()
const available = ref(true)
const mode = ref<ClockMode>('REALTIME')
const window = ref<TimeWindow>({})
const metric = ref('RUNS')
const columns = computed(() => metric.value === 'RUNS'
  ? [{ key: 'total_runs', label: '总运行', series: 'total' }, { key: 'success_runs', label: '成功', series: 'success' }, { key: 'failed_runs', label: '失败', series: 'failed' }]
  : [{ key: 'input_tokens', label: '输入 Token', series: 'total' }, { key: 'output_tokens', label: '输出 Token', series: 'success' }])
const maximum = computed(() => Math.max(1, ...(series.data.value ?? []).flatMap(point =>
  columns.value.map(column => Number(point[column.key] ?? 0)))))
const examples = computed(() => {
  const runs = request.data.value?.recent_runs ?? []
  return [
    { label: '成功运行', run: runs.find(run => run.status === 'SUCCESS') },
    { label: '失败后恢复', run: runs.find(run => run.status === 'SUCCESS' && (run.recovery_count > 0 || run.error_count > 0)) },
    { label: '并行运行', run: demos.data.value },
    { label: '取消运行', run: runs.find(run => run.status === 'CANCELLED') },
  ]
})
const metrics = computed(() => {
  const stats = request.data.value
  return stats ? [
    ['总运行', count(stats.total_runs)], ['运行中', count(stats.running_runs)], ['排队中', count(stats.queued_runs)],
    ['成功', count(stats.success_runs)], ['失败', count(stats.failed_runs)], ['取消', count(stats.cancelled_runs)],
    ['成功率（成功 / 成功与失败）', percent(stats.success_rate)], ['平均执行耗时', ms(stats.avg_execution_duration_ms)],
    ['P50 执行耗时', ms(stats.p50_execution_duration_ms)], ['P95 执行耗时', ms(stats.p95_execution_duration_ms)],
    ['输入 Token', count(stats.input_tokens)], ['输出 Token', count(stats.output_tokens)], ['Span', count(stats.total_spans)],
  ] : []
})
function loadSeries() {
  const end = window.value.to ?? new Date().toISOString()
  const start = window.value.from ?? new Date(Date.parse(end) - 7 * 86400000).toISOString()
  if (Date.parse(end) - Date.parse(start) > 366 * 86400000) {
    series.cancel()
    series.data.value = null
    series.error.value = '趋势区间最多 366 天，请缩小时间窗口。'
    return
  }
  void series.load(signal => v2.series({ from: start, to: end, metric: metric.value, granularity: 'DAY', mode: mode.value }, signal))
}
function load() {
  void request.load(async signal => {
    try {
      const overview = await v2.overview({ ...window.value, mode: mode.value }, signal)
      signal.throwIfAborted()
      available.value = true
      loadSeries()
      void demos.load(async demoSignal => {
        const candidates = new Map<string, OverviewV2['recent_runs'][number]>()
        for (const run of overview.recent_runs) {
          if (run.version_id && !candidates.has(run.version_id)) candidates.set(run.version_id, run)
        }
        for (const [id, run] of [...candidates].slice(0, 8)) {
          const version = await v2.version(id, demoSignal)
          if (version.definition.scenario === 'PARALLEL_RETRIEVAL') return run
        }
        return null
      })
      return overview
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404 && !signal.aborted) available.value = false
      throw cause
    }
  })
}
function apply(value: TimeWindow) { window.value = value; load() }
onMounted(load)
</script>

<template>
  <template v-if="!available">
    <p class="subpanel">当前服务提供 v1 数据。<a href="#/quick">快速模拟执行</a></p>
    <OverviewPage />
  </template>
  <template v-else>
    <header class="page-heading"><h1>运行总览</h1><p>查看队列、运行结果和数据规模。</p></header>
    <section class="card">
      <div class="section-heading"><h2>统计窗口</h2><label>数据来源 <select v-model="mode" @change="load"><option>REALTIME</option><option>VIRTUAL</option><option>LEGACY</option></select></label></div>
      <TimeFilter @apply="apply" />
    </section>
    <LoadState :loading="request.loading.value" :error="request.error.value" @retry="load">
      <template v-if="request.data.value">
        <section class="card"><h2>运行指标</h2>
          <div class="metrics"><div v-for="[label, value] in metrics" :key="label" class="metric"><span>{{ label }}</span><strong>{{ value }}</strong></div></div>
          <p>聚合快照 {{ time(request.data.value.aggregate_status.snapshot_at) }} · 水位 {{ request.data.value.aggregate_status.watermark_max_seq }} · {{ request.data.value.aggregate_status.stale ? '有更新待聚合' : '已同步' }}</p>
          <JsonDetails label="数据集规模" :value="request.data.value.dataset_counts" />
        </section>
        <section class="card">
          <div class="section-heading"><h2>近期运行</h2><a href="#/run-center">打开运行中心</a></div>
          <ul v-if="request.data.value.recent_runs.length">
            <li v-for="run in request.data.value.recent_runs" :key="run.run_id">
              <a :href="traceLink(run.run_id)">{{ run.workflow_name ?? run.run_id }}</a>
              · {{ run.status }} / {{ run.execution_state ?? '—' }} · 排队 {{ ms(run.queue_duration_ms) }} · 执行 {{ ms(run.execution_duration_ms) }}
            </li>
          </ul>
          <p v-else class="empty">暂无近期运行。</p>
          <div class="actions"><a v-for="status in ['RUNNING', 'FAILED', 'CANCELLED', 'SUCCESS']" :key="status" :href="link('run-center', { status, mode })">{{ status }}</a></div>
          <h3>示例轨迹</h3>
          <ul class="v2-demo-links"><li v-for="example in examples" :key="example.label">
            <a v-if="example.run" :href="traceLink(example.run.run_id)">{{ example.label }}</a>
            <span v-else class="muted">{{ example.label }} · {{ example.label === '并行运行' && demos.loading.value ? '查询中' : '近期无记录' }}</span>
          </li></ul>
        </section>
        <section class="card">
          <h2>日趋势</h2><p>按 UTC 日显示，未设时间时查看最近七天。</p>
          <label>指标 <select v-model="metric" @change="loadSeries"><option>RUNS</option><option>TOKENS</option></select></label>
          <LoadState :loading="series.loading.value" :error="series.error.value" :empty="!series.data.value?.length" @retry="loadSeries">
            <div class="chart-legend"><span v-for="column in columns" :key="column.key" :class="['legend', column.series]">{{ column.label }}</span></div>
            <div class="chart-scroll"><ol class="trend-chart">
              <li v-for="(point, index) in series.data.value" :key="index">
                <div class="chart-bars">
                  <span v-for="column in columns" :key="column.key" :class="column.series"
                    :title="column.label + ' ' + String(point[column.key] ?? '—')"
                    :style="{ height: (Number(point[column.key] ?? 0) / maximum * 100) + '%' }"></span>
                </div>
                <small>{{ String(point.date).slice(5) }}</small>
              </li>
            </ol></div>
            <JsonDetails label="查看逐日数据" :value="series.data.value" />
          </LoadState>
        </section>
      </template>
    </LoadState>
  </template>
</template>
