<script setup lang="ts">
defineProps<{ label: string; value: unknown }>()
</script>

<template>
  <details><summary>{{ label }}</summary><pre class="v2-json">{{ JSON.stringify(value, null, 2) }}</pre></details>
</template>
