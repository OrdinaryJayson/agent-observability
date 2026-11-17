<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ label: string; path: string; errors: ReadonlyMap<string, string[]> }>()
const id = computed(() => 'workflow-field' + props.path)
const errorId = computed(() => id.value + '-error')
const messages = computed(() => props.errors.get(props.path))
const attrs = computed(() => ({
  id: id.value,
  'aria-invalid': messages.value?.length ? true : undefined,
  'aria-describedby': messages.value?.length ? errorId.value : undefined,
}))
</script>

<template>
  <div class="v2-workflow-field">
    <label :for="id">{{ label }}</label>
    <slot :attrs="attrs" />
    <small v-if="messages?.length" :id="errorId" class="error">{{ messages.join('；') }}</small>
  </div>
</template>
