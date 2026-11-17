<script setup lang="ts">
import { computed, ref } from 'vue'
import LoadState from '../components/LoadState.vue'
import { useRequest } from '../composables/requests'
import { count, ms } from '../utils/format'
import { v2 } from './api'
import type { CaseCode, Experiment, Trial } from './types'

const props = defineProps<{ experiments: Experiment[] }>()
const chosen = ref<Experiment[]>([])
const results = useRequest<{ experiment: Experiment; spans: number | null; trials: Trial[] }[]>()
const axis = ref('spans')
const first = computed(() => chosen.value[0])
const series = computed(() => {
  const groups = new Map<string, { x: number; y: number; run: string; n: number }[]>()
  for (const { experiment, spans, trials } of results.data.value ?? []) {
    const x = axis.value === 'spans' ? spans : experiment.config.parameters[axis.value]
    if (typeof x !== 'number') continue
    for (const trial of trials) {
      const y = trial.summary.median_ms
      if (typeof y !== 'number') continue
      const values = groups.get(trial.variant) ?? []
      values.push({ x, y, run: experiment.experiment_id, n: trial.summary.n })
      groups.set(trial.variant, values)
    }
  }
  return [...groups].map(([variant, values]) => ({ variant, points: values.sort((a, b) => a.x - b.x) }))
})
const axes: Partial<Record<CaseCode, { key: string; label: string }>> = {
  INDEX_SELECTIVITY: { key: 'selectivity', label: '选择率' },
  JSONB_GIN: { key: 'selectivity', label: '选择率' },
  PAGINATION: { key: 'rank', label: '分页位置' },
  AGGREGATION: { key: 'window_days', label: '窗口天数' },
  QUEUE_CONTENTION: { key: 'claimers', label: '领取者数' },
}

function compatible(row: Experiment) {
  const baseline = first.value
  return row.status === 'SUCCESS' && row.case_code !== 'MVCC_ISOLATION'
    && (!baseline || (baseline.case_code === row.case_code && baseline.protocol_version === row.protocol_version
      && baseline.config.parameters.query === row.config.parameters.query))
}

function toggle(row: Experiment) {
  results.cancel()
  results.data.value = null
  if (chosen.value.some(item => item.experiment_id === row.experiment_id)) {
    chosen.value = chosen.value.filter(item => item.experiment_id !== row.experiment_id)
  } else if (compatible(row) && chosen.value.length < 6) chosen.value.push(row)
  axis.value = 'spans'
}

function load() {
  if (chosen.value.length < 2) return
  const selection = [...chosen.value]
  void results.load(signal => Promise.all(selection.map(async experiment => {
    const dataset = await v2.dataset(experiment.dataset_id, signal)
    const trials: Trial[] = []
    const seen = new Set<string>()
    let cursor: string | undefined
    do {
      const page = await v2.trials(experiment.experiment_id, cursor, signal)
      trials.push(...page.data)
      cursor = page.meta.has_more ? page.meta.next_cursor ?? undefined : undefined
      if (cursor) {
        if (seen.has(cursor)) throw new Error('实验方案分页返回了重复游标')
        seen.add(cursor)
      }
    } while (cursor)
    return { experiment, spans: dataset.actual_counts.spans ?? null, trials }
  })))
}
const range = computed(() => {
  const points = series.value.flatMap(item => item.points)
  const xs = points.map(point => point.x)
  return { min: Math.min(...xs), max: Math.max(...xs), y: Math.max(1, ...points.map(point => point.y)) }
})
function coordinates(x: number, y: number) {
  const value = range.value
  return {
    left: value.min === value.max ? 50 : (x - value.min) / (value.max - value.min) * 100,
    top: 100 - (y / value.y) * 100,
  }
}
function segment(start: { x: number; y: number }, end: { x: number; y: number }) {
  const a = coordinates(start.x, start.y)
  const b = coordinates(end.x, end.y)
  return {
    left: a.left + '%', width: (b.left - a.left) + '%',
    clipPath: `polygon(0 ${a.top}%, 100% ${b.top}%, 100% calc(${b.top}% + 2px), 0 calc(${a.top}% + 2px))`,
  }
}
</script>

<template>
  <details class="subpanel">
    <summary>对比历史实验参数</summary>
    <p>选择 2–6 个同案例、同协议的完成实验。不同数据集或环境的测量需要结合原始记录分析。</p>
    <ul v-if="chosen.length" class="v2-demo-links">
      <li v-for="row in chosen" :key="row.experiment_id"><button class="link-button" @click="toggle(row)">移除 {{ row.experiment_id }}</button></li>
    </ul>
    <label v-for="row in experiments" :key="row.experiment_id" class="check">
      <input type="checkbox" :checked="chosen.some(item => item.experiment_id === row.experiment_id)"
        :disabled="!compatible(row) || (chosen.length >= 6 && !chosen.some(item => item.experiment_id === row.experiment_id))" @change="toggle(row)" />
      {{ row.case_code }} · <span class="v2-id">{{ row.experiment_id }}</span>
    </label>
    <button class="secondary" :disabled="chosen.length < 2 || results.loading.value" @click="load">读取方案并对比</button>
    <LoadState :loading="results.loading.value" :error="results.error.value" @retry="load">
      <template v-if="results.data.value">
        <label>横轴 <select v-model="axis"><option value="spans">实际 Span 数</option>
          <option v-if="first && axes[first.case_code]" :value="axes[first.case_code]?.key">{{ axes[first.case_code]?.label }}</option>
        </select></label>
        <p v-if="!series.length">方案没有该维度与耗时的共同测量。</p>
        <figure v-for="item in series" :key="item.variant" class="v2-samples">
          <figcaption>{{ item.variant }} · 中位耗时（ms）</figcaption>
          <div class="v2-sweep-plot" aria-hidden="true">
            <span v-for="(point, index) in item.points.slice(1)" :key="'line:' + point.run" class="v2-sweep-line"
              :style="segment(item.points[index], point)"></span>
            <span v-for="point in item.points" :key="point.run" class="v2-sweep-point"
              :style="{ left: coordinates(point.x, point.y).left + '%', top: coordinates(point.x, point.y).top + '%' }"></span>
          </div>
          <div class="table-wrap"><table><thead><tr><th>横轴</th><th>中位耗时</th><th>样本数</th><th>实验 ID</th></tr></thead><tbody>
            <tr v-for="point in item.points" :key="point.run"><td>{{ point.x }}</td><td>{{ ms(point.y) }}</td><td>{{ count(point.n) }}</td><td>{{ point.run }}</td></tr>
          </tbody></table></div>
        </figure>
      </template>
    </LoadState>
  </details>
</template>
