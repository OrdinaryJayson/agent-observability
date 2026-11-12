<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import LoadState from '../components/LoadState.vue'
import PageNav from '../components/PageNav.vue'
import TimeFilter from '../components/TimeFilter.vue'
import { usePage } from '../composables/requests'
import type { TimeWindow } from '../types'
import { count, ms, percent } from '../utils/format'

const window = ref<TimeWindow>({})
const agents = usePage((page, signal) => api.agentStats(page, window.value, signal))
const tools = usePage((page, signal) => api.toolStats(page, window.value, signal))
const errorRate = (errors: number, spans: number) => percent(spans ? errors / spans : null)

function apply(next: TimeWindow) {
  window.value = next
  void agents.load(1)
  void tools.load(1)
}

onMounted(() => apply({}))
</script>

<template>
  <header class="page-heading">
    <p class="eyebrow">PERFORMANCE</p>
    <h1>性能分析</h1>
    <p>按 Agent 和工具比较调用次数、错误率和耗时。</p>
  </header>
  <section class="card">
    <h2>统计时间窗口</h2>
    <TimeFilter @apply="apply" />
  </section>
  <section class="card">
    <h2>Agent 性能</h2>
    <p class="muted">调用和耗时按 AGENT Span 统计。Token 来自关联的 LLM Span。</p>
    <LoadState :loading="agents.loading.value" :error="agents.error.value" :empty="!agents.items.value.length" empty-text="该时间窗口暂无已关联 Agent 的统计。" @retry="agents.load()">
      <div class="table-wrap">
        <table>
          <thead><tr><th>Agent</th><th>调用次数</th><th>错误数 / 率</th><th>平均耗时</th><th>输入 Token</th><th>输出 Token</th></tr></thead>
          <tbody>
            <tr v-for="agent in agents.items.value" :key="agent.agent_id">
              <td>{{ agent.name }}<small>{{ agent.agent_id }}</small></td>
              <td>{{ count(agent.span_count) }}</td>
              <td>{{ count(agent.error_count) }} / {{ errorRate(agent.error_count, agent.span_count) }}</td>
              <td>{{ ms(agent.avg_duration_ms) }}</td>
              <td>{{ count(agent.total_input_tokens) }}</td><td>{{ count(agent.total_output_tokens) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </LoadState>
    <PageNav v-if="agents.meta.value" :meta="agents.meta.value" label="Agent 性能分页" @change="agents.load" />
  </section>
  <section class="card">
    <h2>工具性能</h2>
    <p class="muted">按 TOOL Span 的工具名称分组，耗时单位为毫秒。</p>
    <LoadState :loading="tools.loading.value" :error="tools.error.value" :empty="!tools.items.value.length" empty-text="该时间窗口暂无工具调用统计。" @retry="tools.load()">
      <div class="table-wrap">
        <table>
          <thead><tr><th>工具</th><th>调用次数</th><th>错误数 / 率</th><th>平均耗时</th><th>总耗时</th></tr></thead>
          <tbody>
            <tr v-for="tool in tools.items.value" :key="tool.tool_name ?? ''">
              <td>{{ tool.tool_name ?? '未命名' }}</td><td>{{ count(tool.span_count) }}</td>
              <td>{{ count(tool.error_count) }} / {{ errorRate(tool.error_count, tool.span_count) }}</td>
              <td>{{ ms(tool.avg_duration_ms) }}</td><td>{{ ms(tool.total_duration_ms) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </LoadState>
    <PageNav v-if="tools.meta.value" :meta="tools.meta.value" label="工具性能分页" @change="tools.load" />
  </section>
</template>
