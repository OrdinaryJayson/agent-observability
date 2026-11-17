<script setup lang="ts">
defineProps<{ back: boolean; forward: boolean; loading: boolean }>()
defineEmits<{ previous: []; next: [] }>()
</script>

<template>
  <nav class="pagination" aria-label="游标分页">
    <button type="button" class="secondary" :disabled="!back || loading" @click="$emit('previous')">上一页</button>
    <button type="button" class="secondary" :disabled="!forward || loading" @click="$emit('next')">下一页</button>
  </nav>
</template>
