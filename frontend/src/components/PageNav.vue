<script setup lang="ts">
import { computed } from 'vue'
import type { Page } from '../types'

const props = defineProps<{ meta: Page<unknown>['meta']; label: string }>()
const emit = defineEmits<{ change: [page: number] }>()
const pages = computed(() => Math.max(1, Math.ceil(props.meta.total / props.meta.page_size)))
</script>

<template>
  <nav class="pagination" :aria-label="label">
    <button type="button" class="secondary" :disabled="meta.page <= 1" @click="emit('change', meta.page - 1)">上一页</button>
    <span>第 {{ meta.page }} / {{ pages }} 页 · 共 {{ meta.total }} 条</span>
    <button type="button" class="secondary" :disabled="meta.page >= pages" @click="emit('change', meta.page + 1)">下一页</button>
  </nav>
</template>
