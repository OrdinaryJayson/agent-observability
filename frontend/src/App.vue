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
const navigation: { label: string; links: [url: string, label: string, icon: string][] }[] = [
  {
    label: '工作台',
    links: [
      ['/', '快速执行', 'm13 2-8 12h6l-1 8 9-12h-6l1-8Z'],
      ['/overview', '运行总览', 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z'],
    ],
  },
  {
    label: '运行管理',
    links: [
      ['/agents', 'Agent 管理', 'M5 8h14v12H5z M12 4v4 M9 13h.01 M15 13h.01 M9 17h6 M2 12v4 M22 12v4'],
      ['/tasks', '任务管理', 'M8 5h12 M8 12h12 M8 19h12 M3 5h.01 M3 12h.01 M3 19h.01'],
      ['/runs', '运行历史', 'M4 12a8 8 0 1 1 2.4 5.7 M4 5v7h7 M12 8v5l3 2'],
      ['/trace', '执行轨迹', 'M4 3h5v5H4z M15 10h5v5h-5z M15 17h5v5h-5z M6.5 8v11.5H15 M6.5 12.5H15'],
      ['/logs', '全局日志', 'M6 3h9l4 4v14H6z M14 3v5h5 M9 12h7 M9 16h7'],
    ],
  },
  {
    label: '数据分析',
    links: [
      ['/performance', '性能分析', 'M4 5v14h16 M7 14l4-4 4 2 5-6'],
      ['/benchmarks', '索引实验', 'M9 3h6 M10 3v7l-6 9a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2l-6-9V3 M8 15h8'],
    ],
  },
]

const hash = ref(location.hash)
const path = computed(() => hash.value.slice(1).split('?')[0] || '/')
const params = computed(() => new URLSearchParams(hash.value.split('?')[1] || ''))
const currentPage = computed(() =>
  navigation.flatMap(group => group.links).find(([url]) => url === path.value)?.[1] ?? '页面不存在',
)

function navigate() {
  hash.value = location.hash
  window.scrollTo(0, 0)
}

window.addEventListener('hashchange', navigate)
onBeforeUnmount(() => window.removeEventListener('hashchange', navigate))
</script>

<template>
  <div class="console-layout">
    <aside class="app-sidebar">
      <a class="brand" :href="quickExecutionHref">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M7.5 6.5 16.5 12l-9 5.5M6 8v8" />
            <circle cx="6" cy="5" r="2" /><circle cx="18" cy="12" r="2" /><circle cx="6" cy="19" r="2" />
          </svg>
        </span>
        <span class="brand-wordmark">Agent Observability<small>执行观测控制台</small></span>
      </a>
      <nav class="app-nav" aria-label="主导航">
        <div v-for="group in navigation" :key="group.label" class="nav-group">
          <p class="nav-label">{{ group.label }}</p>
          <a v-for="[url, label, icon] in group.links" :key="url" :href="'#' + url" :aria-current="path === url ? 'page' : undefined">
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">
              <path :d="icon" />
            </svg>
            {{ label }}
          </a>
        </div>
      </nav>
    </aside>
    <div class="workspace">
      <div class="workspace-bar">
        <span class="breadcrumb"><span>控制台</span><span aria-hidden="true">/</span><strong>{{ currentPage }}</strong></span>
        <span class="workspace-zone" :title="'本地时区 ' + timeZone">
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
            <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
          </svg>
          {{ timeZone }}
        </span>
      </div>
      <main class="workspace-content">
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
        <footer class="app-footer">Agent Observability <span>·</span> 本地时区 {{ timeZone }}</footer>
      </main>
    </div>
  </div>
</template>
