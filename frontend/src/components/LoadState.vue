<script setup lang="ts">
defineProps<{ loading: boolean; error: string; empty?: boolean; emptyText?: string }>()
const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <p v-if="loading" class="muted" role="status">加载中…</p>
  <div v-else-if="error" class="notice error">
    <p role="alert">{{ error }}</p>
    <button type="button" class="secondary" @click="emit('retry')">重试</button>
  </div>
  <p v-else-if="empty" class="empty">{{ emptyText || '暂无记录。' }}</p>
  <slot v-else />
</template>
