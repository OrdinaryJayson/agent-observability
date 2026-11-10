<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import AgentsPage from './pages/AgentsPage.vue'
import BenchmarksPage from './pages/BenchmarksPage.vue'
import LogsPage from './pages/LogsPage.vue'
import OverviewPage from './pages/OverviewPage.vue'
import PerformancePage from './pages/PerformancePage.vue'
import RunsPage from './pages/RunsPage.vue'
import TasksPage from './pages/TasksPage.vue'
import TracePage from './pages/TracePage.vue'
import { timeZone } from './utils/format'

const quickExecutionHref = '#/'
const links = [
  ['/', '快速执行'], ['/overview', '运行总览'], ['/agents', 'Agent 管理'],
  ['/tasks', '任务管理'], ['/runs', '运行历史'], ['/trace', '执行轨迹'],
  ['/logs', '全局日志'], ['/performance', '性能分析'], ['/benchmarks', '索引实验'],
] as const

const hash = ref(location.hash)
const path = computed(() => hash.value.slice(1).split('?')[0] || '/')
const params = computed(() => new URLSearchParams(hash.value.split('?')[1] || ''))

function navigate() {
  hash.value = location.hash
  window.scrollTo(0, 0)
}

window.addEventListener('hashchange', navigate)
onBeforeUnmount(() => window.removeEventListener('hashchange', navigate))
</script>

<template>
  <header class="app-header">
    <div class="app-header-inner">
      <a class="brand" :href="quickExecutionHref">Agent Observability</a>
      <nav class="app-nav" aria-label="主导航">
        <a v-for="[url, label] in links" :key="url" :href="'#' + url" :aria-current="path === url ? 'page' : undefined">{{ label }}</a>
      </nav>
    </div>
  </header>
  <main>
    <TracePage v-if="path === '/'" key="quick" quick />
    <OverviewPage v-else-if="path === '/overview'" />
    <AgentsPage v-else-if="path === '/agents'" />
    <TasksPage v-else-if="path === '/tasks'" />
    <RunsPage v-else-if="path === '/runs'" :key="'runs:' + hash" :initial-task-id="params.get('task') ?? undefined" />
    <TracePage
      v-else-if="path === '/trace'" :key="'trace:' + hash"
      :run-id="params.get('run') ?? undefined" :span-id="params.get('span') ?? undefined" :event-id="params.get('event') ?? undefined"
    />
    <LogsPage v-else-if="path === '/logs'" />
    <PerformancePage v-else-if="path === '/performance'" />
    <BenchmarksPage v-else-if="path === '/benchmarks'" />
    <section v-else class="card"><h1>页面不存在</h1><p><a :href="quickExecutionHref">返回快速执行</a></p></section>
    <footer class="app-footer">Agent Observability · 本地时区 {{ timeZone }}</footer>
  </main>
</template>
