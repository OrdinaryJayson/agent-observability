<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watchEffect } from 'vue'
import { layoutGraph, nodeHeight, nodeWidth, type GraphEdge, type GraphNode } from './graph'

const props = defineProps<{ nodes: GraphNode[]; edges: GraphEdge[]; selected?: string; highlight?: string[]; highlightLinks?: boolean }>()
const emit = defineEmits<{ select: [id: string] }>()
const viewport = ref<HTMLElement>()
const canvas = ref<HTMLCanvasElement>()
const zoom = ref(1)
const query = ref('')
const graph = computed(() => layoutGraph(props.nodes, props.edges))
const highlighted = computed(() => new Set(props.highlight))
const nextOnPath = computed(() => new Map(props.highlight?.slice(0, -1).map((id, index) => [id, props.highlight![index + 1]])))
const width = computed(() => Math.ceil(graph.value.width * zoom.value))
const height = computed(() => Math.ceil(graph.value.height * zoom.value))
const visible = ref({ x: 0, y: 0, width: 1, height: 1 })
let observer: ResizeObserver | undefined

function measure() {
  const element = viewport.value
  if (element) visible.value = {
    x: element.scrollLeft, y: element.scrollTop,
    width: Math.max(1, Math.min(width.value, element.clientWidth)),
    height: Math.max(1, Math.min(height.value, element.clientHeight)),
  }
}

function fit() {
  if (viewport.value) zoom.value = Math.min(1, Math.max(.35, (viewport.value.clientWidth - 2) / graph.value.width))
  viewport.value?.scrollTo(0, 0)
  measure()
}

function locate() {
  const term = query.value.trim().toLowerCase()
  if (!term) return
  const match = graph.value.positions.find(node => (node.label + ' ' + node.id).toLowerCase().includes(term))
  if (!match) return
  emit('select', match.id)
  viewport.value?.scrollTo({ left: Math.max(0, match.x * zoom.value - 20), top: Math.max(0, match.y * zoom.value - 20) })
}

onMounted(() => {
  fit()
  observer = new ResizeObserver(measure)
  if (viewport.value) observer.observe(viewport.value)
})
onBeforeUnmount(() => observer?.disconnect())
watchEffect(() => { width.value; height.value; measure() }, { flush: 'post' })
watchEffect(() => {
  const element = canvas.value
  const context = element?.getContext('2d')
  if (!context) return
  const scale = zoom.value
  const geometry = graph.value
  const area = visible.value
  context.resetTransform()
  context.clearRect(0, 0, area.width, area.height)
  context.setTransform(scale, 0, 0, scale, -area.x, -area.y)
  context.font = '11px system-ui'
  const positions = new Map(geometry.positions.map(node => [node.id, node]))
  for (const edge of geometry.edges) {
    const source = positions.get(edge.source)
    const target = positions.get(edge.target)
    if (!source || !target) continue
    const x = source.x + nodeWidth, y = source.y + nodeHeight / 2
    const endX = target.x, endY = target.y + nodeHeight / 2
    const bend = Math.max(24, Math.abs(endX - x) / 2)
    const accent = props.highlightLinks && nextOnPath.value.get(source.id) === target.id
    context.strokeStyle = accent ? '#995b16' : '#668c81'
    context.lineWidth = accent ? 2.5 : 1.4
    context.beginPath()
    context.moveTo(x, y)
    context.bezierCurveTo(x + bend, y, endX - bend, endY, endX - 2, endY)
    context.lineTo(endX - 9, endY - 4)
    context.moveTo(endX - 2, endY)
    context.lineTo(endX - 9, endY + 4)
    context.stroke()
    if (edge.label) {
      context.fillStyle = '#314f46'
      context.fillText(edge.label, (x + endX) / 2 - 15, (y + endY) / 2 - 5)
    }
  }
}, { flush: 'post' })
</script>

<template>
  <div class="v2-graph">
    <div class="actions v2-toolbar">
      <button type="button" class="secondary" @click="zoom = Math.max(.35, zoom - .15)" aria-label="缩小图">−</button>
      <button type="button" class="secondary" @click="zoom = Math.min(1.75, zoom + .15)" aria-label="放大图">+</button>
      <button type="button" class="secondary" @click="fit">适配视口</button>
      <small>{{ Math.round(zoom * 100) }}% · {{ nodes.length }} 个节点</small>
      <div class="actions">
        <input v-model="query" aria-label="搜索节点" placeholder="节点名称或标识" @keydown.enter.prevent="locate" />
        <button type="button" class="secondary" @click="locate">定位</button>
      </div>
    </div>
    <div ref="viewport" class="graph-viewport" tabindex="0" aria-label="节点连线图，可滚动" @scroll="measure">
      <div class="graph-stage" :style="{ width: width + 'px', height: height + 'px' }">
        <canvas ref="canvas" :width="visible.width" :height="visible.height"
          :style="{ left: visible.x + 'px', top: visible.y + 'px' }" aria-hidden="true" />
        <div class="graph-nodes" :style="{ transform: 'scale(' + zoom + ')' }">
          <button v-for="node in graph.positions" :key="node.id" type="button"
            :class="['graph-node', { 'graph-highlight': highlighted.has(node.id), 'graph-failed': node.status === 'ERROR' }]"
            :style="{ left: node.x + 'px', top: node.y + 'px', width: nodeWidth + 'px', height: nodeHeight + 'px' }"
            :aria-pressed="selected === node.id" :title="node.label + (node.caption ? ' · ' + node.caption : '')" @click="emit('select', node.id)">
            <strong>{{ node.label }}</strong>
            <small v-if="node.status" :class="['badge', node.status]">{{ node.status }}</small>
            <small v-else>{{ node.caption }}</small>
          </button>
        </div>
      </div>
      <p v-if="!nodes.length" class="empty">暂无节点。</p>
    </div>
  </div>
</template>
