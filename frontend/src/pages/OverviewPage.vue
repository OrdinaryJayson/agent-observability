<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client'
import LoadState from '../components/LoadState.vue'
import PageNav from '../components/PageNav.vue'
import TimeFilter from '../components/TimeFilter.vue'
import { usePage, useRequest } from '../composables/requests'
import type { Overview, TimeWindow, TrendPoint } from '../types'
import { count, ms, percent } from '../utils/format'
import { trendCalendar, trendDays } from '../utils/trend'

const window = ref<TimeWindow>({})
const { data: stats, loading, error, load } = useRequest<Overview>()
const { data: trend, loading: trendLoading, error: trendError, load: loadTrend } = useRequest<TrendPoint[]>()
const errors = usePage((page, signal) => api.errors(page, window.value, signal))
const dayPage = ref(1)
const daysPerPage = 14
const calendar = computed(() => trendCalendar(trend.value ?? [], window.value))
const days = computed(() => trendDays(calendar.value, (dayPage.value - 1) * daysPerPage, daysPerPage))
const totalDays = computed(() => calendar.value?.length ?? 0)
const maxRuns = computed(() => Math.max(1, ...days.value.map(day => day.total_runs)))
const maxErrors = computed(() => Math.max(1, ...errors.items.value.map(item => item.count)))

const metrics = computed(() => {
  const value = stats.value
  if (!value) return []
  return [
    { label: '总运行数', value: count(value.total_runs) },
    { label: '成功运行', value: count(value.success_runs) },
    { label: '失败运行', value: count(value.failed_runs) },
    { label: '成功率', value: percent(value.success_rate) },
    { label: '失败率', value: percent(value.success_rate === null ? null : 1 - value.success_rate) },
    { label: '平均耗时', value: ms(value.avg_duration_ms) },
    { label: 'P50 耗时', value: ms(value.p50_duration_ms) },
    { label: 'P95 耗时', value: ms(value.p95_duration_ms) },
    { label: '输入 Token', value: count(value.total_input_tokens) },
    { label: '输出 Token', value: count(value.total_output_tokens) },
    { label: '总 Span 数', value: count(value.total_spans) },
  ]
})

const refreshOverview = () => load(async signal => (await api.overview(window.value, signal)).data)
const refreshTrend = () => loadTrend(signal => api.trend(window.value, signal))

function apply(next: TimeWindow) {
  window.value = next
  dayPage.value = 1
  void refreshOverview()
  void refreshTrend()
  void errors.load(1)
}

onMounted(() => apply({}))
</script>

<template>
  <header class="page-heading">
    <p class="eyebrow">OVERVIEW</p>
    <h1>运行总览</h1>
    <p>查看运行结果、耗时、Token 和异常分布。</p>
  </header>
  <section class="card">
    <h2>统计时间窗口</h2>
    <TimeFilter @apply="apply" />
  </section>
  <section class="card">
    <h2>运行指标</h2>
    <LoadState :loading="loading" :error="error" @retry="refreshOverview">
      <div class="metrics">
        <div v-for="metric in metrics" :key="metric.label" class="metric">
          <span>{{ metric.label }}</span><strong>{{ metric.value }}</strong>
        </div>
      </div>
      <p v-if="stats?.total_runs === 0" class="muted">该时间窗口暂无运行。</p>
      <p class="muted">成功率和失败率仅按已成功或失败的运行计算。</p>
    </LoadState>
  </section>
  <section class="card">
    <h2>每日运行趋势</h2>
    <p class="muted">按 UTC 日期统计，缺失日期补零。</p>
    <LoadState :loading="trendLoading" :error="trendError" :empty="!days.length" empty-text="暂无运行趋势。" @retry="refreshTrend">
      <div class="chart-legend">
        <span class="legend total">总运行</span><span class="legend success">成功</span><span class="legend failed">失败</span>
      </div>
      <div class="chart-scroll">
        <ol class="trend-chart" aria-label="每日总运行、成功和失败次数">
          <li
            v-for="day in days" :key="day.date"
            :aria-label="`${day.date} 总运行 ${day.total_runs}，成功 ${day.success_runs}，失败 ${day.failed_runs}`"
            :title="`${day.date} · 总运行 ${day.total_runs} · 成功 ${day.success_runs} · 失败 ${day.failed_runs}`"
          >
            <div class="chart-bars" aria-hidden="true">
              <span class="total" :style="{ height: (day.total_runs / maxRuns * 100) + '%' }"></span>
              <span class="success" :style="{ height: (day.success_runs / maxRuns * 100) + '%' }"></span>
              <span class="failed" :style="{ height: (day.failed_runs / maxRuns * 100) + '%' }"></span>
            </div>
            <small>{{ day.date.slice(5) }}</small>
          </li>
        </ol>
      </div>
      <details><summary>查看趋势数据</summary>
        <div class="table-wrap">
          <table>
            <thead><tr><th>日期（UTC）</th><th>总运行</th><th>成功</th><th>失败</th></tr></thead>
            <tbody><tr v-for="day in days" :key="day.date"><td>{{ day.date }}</td><td>{{ day.total_runs }}</td><td>{{ day.success_runs }}</td><td>{{ day.failed_runs }}</td></tr></tbody>
          </table>
        </div>
      </details>
    </LoadState>
    <PageNav v-if="totalDays > daysPerPage" :meta="{ page: dayPage, page_size: daysPerPage, total: totalDays }" label="趋势日期分页" @change="dayPage = $event" />
  </section>
  <section class="card">
    <h2>异常分布</h2>
    <LoadState :loading="errors.loading.value" :error="errors.error.value" :empty="!errors.items.value.length" empty-text="该时间窗口暂无异常。" @retry="errors.load()">
      <ul class="distribution">
        <li v-for="item in errors.items.value" :key="item.error_type ?? ''">
          <span>{{ item.error_type ?? '未分类' }}</span>
          <span class="distribution-track" aria-hidden="true"><span :style="{ width: (item.count / maxErrors * 100) + '%' }"></span></span>
          <strong>{{ count(item.count) }}</strong>
        </li>
      </ul>
    </LoadState>
    <PageNav v-if="errors.meta.value" :meta="errors.meta.value" label="异常分布分页" @change="errors.load" />
  </section>
</template>
