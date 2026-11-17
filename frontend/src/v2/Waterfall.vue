<script setup lang="ts">
import { computed, ref } from 'vue'
import { ms } from '../utils/format'
import type { LiveSpan } from './types'

const props = defineProps<{ spans: LiveSpan[]; selected?: string; through?: string }>()
const emit = defineEmits<{ select: [id: string] }>()
const zoom = ref(1)
const ranges = computed(() => props.spans.map(span => ({
  span, start: Date.parse(span.start_time),
  end: Math.max(Date.parse(span.start_time), Date.parse(span.end_time ?? props.through ?? span.start_time)),
})))
const origin = computed(() => ranges.value.length ? Math.min(...ranges.value.map(row => row.start)) : 0)
const total = computed(() => ranges.value.length ? Math.max(...ranges.value.map(row => row.end)) - origin.value : 0)
const duration = computed(() => Math.max(1, total.value))
</script>

<template>
  <div class="actions v2-toolbar">
    <button class="secondary" aria-label="缩小瀑布图" @click="zoom = Math.max(1, zoom - 1)">−</button>
    <button class="secondary" aria-label="放大瀑布图" @click="zoom = Math.min(6, zoom + 1)">+</button>
    <span>相对时间 · {{ zoom }}×</span>
  </div>
  <div class="waterfall-viewport" tabindex="0" aria-label="瀑布图，可滚动">
    <div :style="{ minWidth: (480 * zoom) + 'px' }">
      <div class="waterfall-row waterfall-axis">
        <span>Span</span>
        <div><span v-for="i in 5" :key="i">{{ ms(total * (i - 1) / 4) }}</span></div>
      </div>
      <button v-for="row in ranges" :key="row.span.span_id" type="button" class="waterfall-row"
        :aria-pressed="selected === row.span.span_id" @click="emit('select', row.span.span_id)">
        <span>{{ row.span.span_name }} <small>{{ row.span.state }}</small></span>
        <span class="waterfall-track">
          <span :class="['waterfall-bar', row.span.state]" :title="ms(row.end - row.start)"
            :style="{ left: ((row.start - origin) / duration * 100) + '%', width: ((row.end - row.start) / duration * 100) + '%' }"></span>
        </span>
      </button>
    </div>
  </div>
</template>
