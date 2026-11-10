<script setup lang="ts">
import { ref } from 'vue'
import type { TimeWindow } from '../types'
import { timeZone, utcWindow } from '../utils/format'
import { errorMessage } from '../composables/requests'

const emit = defineEmits<{ apply: [window: TimeWindow] }>()
const from = ref('')
const to = ref('')
const error = ref('')

function apply() {
  error.value = ''
  try {
    emit('apply', utcWindow(from.value, to.value))
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}

function clear() {
  from.value = ''
  to.value = ''
  apply()
}
</script>

<template>
  <form class="filter-row time-filter" @submit.prevent="apply">
    <label>开始时间 <input v-model="from" type="datetime-local" /></label>
    <label>结束时间 <input v-model="to" type="datetime-local" /></label>
    <div class="actions">
      <button>应用时间窗口</button>
      <button type="button" class="secondary" @click="clear">清空时间</button>
    </div>
    <small>本地时间 · {{ timeZone }} · 结束时间不包含在内</small>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
  </form>
</template>
