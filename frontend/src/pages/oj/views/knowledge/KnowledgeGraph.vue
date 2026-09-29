<template>
  <div class="graph-shell" :class="{ dragging: pressed }" ref="shell" @pointerdown="startDrag" @pointermove="moveDrag" @pointerup="endDrag" @pointercancel="cancelDrag" @lostpointercapture="endDrag" @click.capture="blockDragClick">
    <div class="graph-stage">
      <div v-if="!layout.nodes.length" class="graph-empty">当前范围内暂无可显示的知识点</div>
      <svg v-else class="graph-svg" :width="layout.width * scale" :height="layout.height * scale" :viewBox="`0 0 ${layout.width} ${layout.height}`" role="group" aria-label="知识点依赖图">
      <defs><marker :id="markerId" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0 0 L9 4.5 L0 9 Z" fill="#8291a6" /></marker></defs>
      <g v-for="(edge, index) in layout.edges" :key="index">
        <line :x1="edge.x1" :y1="edge.y1" :x2="edge.x2" :y2="edge.y2" stroke="#8291a6" stroke-width="1.8" :stroke-dasharray="edge.relation_type === 'recommended' ? '5 5' : undefined" :marker-end="`url(#${markerId})`" />
      </g>
      <g v-for="node in layout.nodes" :key="node.code" class="graph-node">
        <g class="graph-node-main" tabindex="0" role="button" :aria-label="`以${node.name}为中心查看图谱`" @click="select(node.code)" @keydown.enter="select(node.code)" @keydown.space.prevent="select(node.code)">
          <rect :x="node.x" :y="node.y" width="156" height="52" rx="12" :fill="node.code === rootCode ? '#2d8cf0' : '#f3f7fc'" :stroke="node.code === rootCode ? '#2d8cf0' : '#dce7f3'" />
          <text :x="node.x + 78" :y="node.y + 21" text-anchor="middle" :fill="node.code === rootCode ? '#fff' : '#25364d'" font-size="13" font-weight="600">{{ short(node.name) }}</text>
          <text :x="node.x + 12" :y="node.y + 39" :fill="node.code === rootCode ? '#e7f2ff' : '#8191a5'" font-size="11">{{ short(node.code, 14) }}</text>
        </g>
        <g class="graph-detail-link" tabindex="0" role="link" :aria-label="`查看${node.name}详情`" @click.stop="openDetail(node.code)" @keydown.enter.stop.prevent="openDetail(node.code)" @keydown.space.stop.prevent="openDetail(node.code)">
          <title>查看{{ node.name }}详情</title>
          <rect :x="node.x + 114" :y="node.y + 25" width="34" height="24" fill="transparent" />
          <path :d="`M ${node.x + 129} ${node.y + 32} L ${node.x + 136} ${node.y + 37} L ${node.x + 129} ${node.y + 42}`" fill="none" :stroke="node.code === rootCode ? '#fff' : '#becee0'" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
        </g>
      </g>
      </svg>
    </div>
  </div>
</template>
<script>
  import { layoutKnowledgeGraph } from './knowledgeGraphLayout'

  export default {
    props: {
      graph: { type: Object, required: true },
      rootCode: { type: String, default: '' },
      directional: { type: Boolean, default: false }
    },
    emits: ['select-node'],
    data () { return { scale: 1, pressed: false, dragging: false, dragStart: null, suppressClick: false } },
    mounted () { this.$nextTick(() => this.center()) },
    beforeUnmount () {
      window.removeEventListener('pointerup', this.endDrag)
      window.removeEventListener('pointercancel', this.cancelDrag)
    },
    watch: { layout () { this.scale = 1; this.$nextTick(() => this.center()) } },
    computed: {
      markerId () { return `knowledge-arrow-${this.$.uid}` },
      layout () { return layoutKnowledgeGraph(this.graph, this.rootCode, this.directional) }
    },
    methods: {
      short (value, limit = 12) { return value.length > limit ? value.slice(0, limit - 1) + '…' : value },
      select (code) { this.$emit('select-node', code) },
      openDetail (code) { this.$router.push({ name: 'knowledge-detail', params: { code } }) },
      startDrag (event) {
        if (event.button !== 0 || event.isPrimary === false || !event.target.closest('.graph-stage')) return
        const shell = this.$refs.shell
        this.suppressClick = false
        this.pressed = true
        this.dragStart = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, left: shell.scrollLeft, top: shell.scrollTop }
        window.addEventListener('pointerup', this.endDrag)
        window.addEventListener('pointercancel', this.cancelDrag)
      },
      moveDrag (event) {
        const start = this.dragStart
        if (!start || event.pointerId !== start.pointerId) return
        const dx = event.clientX - start.x
        const dy = event.clientY - start.y
        if (!this.dragging && Math.hypot(dx, dy) < 5) return
        const shell = this.$refs.shell
        if (!this.dragging) {
          this.dragging = true
          this.suppressClick = true
          if (shell.setPointerCapture) shell.setPointerCapture(event.pointerId)
        }
        shell.scrollLeft = start.left - dx
        shell.scrollTop = start.top - dy
        event.preventDefault()
      },
      endDrag (event) {
        if (!this.dragStart || event.pointerId !== this.dragStart.pointerId) return
        const shell = this.$refs.shell
        this.dragStart = null
        this.pressed = false
        this.dragging = false
        window.removeEventListener('pointerup', this.endDrag)
        window.removeEventListener('pointercancel', this.cancelDrag)
        if (shell.hasPointerCapture && shell.hasPointerCapture(event.pointerId)) shell.releasePointerCapture(event.pointerId)
      },
      cancelDrag (event) {
        this.endDrag(event)
        this.suppressClick = false
      },
      blockDragClick (event) {
        if (!this.suppressClick) return
        event.preventDefault()
        event.stopPropagation()
        this.suppressClick = false
      },
      fit () {
        const shell = this.$refs.shell
        if (!shell) return
        this.scale = Math.min(1, (shell.clientWidth - 2) / this.layout.width, (shell.clientHeight - 2) / this.layout.height)
        this.$nextTick(() => this.center())
      },
      zoom (step) {
        this.scale = Math.min(2.5, Math.max(0.25, Math.round((this.scale + step) * 100) / 100))
        this.$nextTick(() => this.center())
      },
      center () {
        const shell = this.$refs.shell
        if (!shell) return
        shell.scrollLeft = Math.max(0, (shell.scrollWidth - shell.clientWidth) / 2)
        shell.scrollTop = Math.max(0, (shell.scrollHeight - shell.clientHeight) / 2)
      }
    }
  }
</script>
<style scoped>
  .graph-shell { width: 100%; height: 100%; min-width: 0; min-height: 0; overflow: auto; background: #fff; cursor: default; }
  .graph-shell.dragging { cursor: grabbing; user-select: none; }
  .graph-stage { display: grid; place-items: center; width: max-content; min-width: 100%; height: max-content; min-height: 100%; touch-action: none; }
  .graph-svg { display: block; }
  .graph-node-main { cursor: default; outline: none; }
  .graph-node-main:focus rect, .graph-node-main:hover rect { stroke: #2d8cf0; stroke-width: 2.5; }
  .graph-detail-link { cursor: pointer; outline: none; }
  .graph-detail-link:hover path, .graph-detail-link:focus path { opacity: .65; }
  .graph-shell.dragging .graph-node-main, .graph-shell.dragging .graph-detail-link { cursor: grabbing; }
  .graph-empty { min-height: 180px; display: grid; place-items: center; color: #8995a5; }
</style>
