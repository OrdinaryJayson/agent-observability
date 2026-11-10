<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import LoadState from '../components/LoadState.vue'
import PageNav from '../components/PageNav.vue'
import { usePage, useRequest } from '../composables/requests'
import { benchmarkCases, type BenchmarkCase, type BenchmarkResult, type DatasetSize } from '../types'
import { count, decimal, ms, time } from '../utils/format'

const sizes: DatasetSize[] = [1000, 10000, 100000]
const caseCode = ref<BenchmarkCase>('TRACE_QUERY_INDEX')
const datasetSize = ref<DatasetSize>(1000)
const { items, meta, loading, error, load } = usePage(api.benchmarks)
const execution = useRequest<BenchmarkResult>()
const { loading: running, error: runError } = execution
const selected = ref<BenchmarkResult | null>(null)

async function run() {
  if (running.value) return
  const code = caseCode.value
  const size = datasetSize.value
  const result = await execution.load(async signal => (await api.runBenchmark(code, size, signal)).data)
  if (result) {
    selected.value = result
    await load(1)
  }
}

function speedup(result: BenchmarkResult) {
  const { duration_before_ms, duration_after_ms } = result.plan
  return duration_after_ms === 0 ? '—' : `${decimal(duration_before_ms / duration_after_ms)}×`
}

onMounted(() => void load())
</script>

<template>
  <header class="page-heading">
    <p class="eyebrow">BENCHMARKS</p>
    <h1>数据库索引实验</h1>
    <p>选择查询和数据规模，比较建索引前后的实际执行计划。</p>
  </header>
  <section class="card">
    <h2>执行实验</h2>
    <form class="filter-row" @submit.prevent="run">
      <label>实验案例
        <select v-model="caseCode" :disabled="running">
          <option v-for="(label, code) in benchmarkCases" :key="code" :value="code">{{ label }}</option>
        </select>
      </label>
      <label>数据规模（Span 行）
        <select v-model="datasetSize" :disabled="running"><option v-for="size in sizes" :key="size" :value="size">{{ count(size) }}</option></select>
      </label>
      <button :disabled="running">{{ running ? '实验运行中…' : '运行实验' }}</button>
    </form>
    <p v-if="running" role="status">正在测量索引前后耗时，请等待服务返回结果。</p>
    <p v-if="runError" role="alert" class="error">{{ runError }}</p>
  </section>
  <section v-if="selected" class="card">
    <h2>实验结果</h2>
    <h3>{{ benchmarkCases[selected.case_code] }}</h3>
    <dl>
      <dt>执行时间</dt><dd>{{ time(selected.created_at) }}</dd>
      <dt>实际规模</dt><dd>{{ count(selected.dataset_size) }} 行</dd>
      <dt>索引策略</dt><dd><code>{{ selected.index_strategy }}</code></dd>
      <dt>测量次数</dt><dd>{{ count(selected.plan.repeats) }} 次，取中位数</dd>
      <dt>耗时（前 / 后）</dt><dd>{{ ms(selected.plan.duration_before_ms) }} / {{ ms(selected.plan.duration_after_ms) }}</dd>
      <dt>加速比</dt><dd>{{ speedup(selected) }}</dd>
    </dl>
    <div class="plan-grid">
      <div><h3>建索引前的执行计划</h3><pre>{{ JSON.stringify(selected.plan.before, null, 2) }}</pre></div>
      <div><h3>建索引后的执行计划</h3><pre>{{ JSON.stringify(selected.plan.after, null, 2) }}</pre></div>
    </div>
  </section>
  <section class="card">
    <h2>实验历史</h2>
    <LoadState :loading="loading" :error="error" :empty="!items.length" empty-text="暂无已完成的实验。" @retry="load()">
      <div class="table-wrap">
        <table>
          <thead><tr><th>实验</th><th>实际规模（行）</th><th>策略</th><th>索引前 / 后</th><th>时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="result in items" :key="result.result_id">
              <td>{{ benchmarkCases[result.case_code] }}</td><td>{{ count(result.dataset_size) }}</td>
              <td><code>{{ result.index_strategy }}</code></td>
              <td>{{ ms(result.plan.duration_before_ms) }} / {{ ms(result.plan.duration_after_ms) }}</td>
              <td>{{ time(result.created_at) }}</td>
              <td><button type="button" class="link-button" @click="selected = result">查看执行计划</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </LoadState>
    <PageNav v-if="meta" :meta="meta" label="实验历史分页" @change="load" />
  </section>
</template>
