<template>
  <div class="graph-shell" ref="shell">
    <div v-if="!graph.nodes.length" class="graph-empty">当前范围内暂无可显示的知识点</div>
    <svg v-else class="graph-svg" :width="width * scale" :height="height * scale" :viewBox="`0 0 ${width} ${height}`" role="img" aria-label="知识点依赖图">
      <defs><marker :id="markerId" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0 0 L9 4.5 L0 9 Z" fill="#8291a6" /></marker></defs>
      <g v-for="(edge, index) in lines" :key="index">
        <line :x1="edge.x1" :y1="edge.y1" :x2="edge.x2" :y2="edge.y2" stroke="#8291a6" stroke-width="1.8" :stroke-dasharray="edge.relation_type === 'recommended' ? '5 5' : undefined" :marker-end="`url(#${markerId})`" />
      </g>
      <g v-for="node in positioned" :key="node.code" class="graph-node" :tabindex="0" role="link" :aria-label="`查看${node.name}详情`" @click="open(node.code)" @keydown.enter="open(node.code)" @keydown.space.prevent="open(node.code)">
        <rect :x="node.x" :y="node.y" width="156" height="52" rx="12" :fill="node.code === rootCode ? '#2d8cf0' : '#f3f7fc'" :stroke="node.code === rootCode ? '#2d8cf0' : '#dce7f3'" />
        <text :x="node.x + 78" :y="node.y + 21" text-anchor="middle" :fill="node.code === rootCode ? '#fff' : '#25364d'" font-size="13" font-weight="600">{{ short(node.name) }}</text>
        <text :x="node.x + 78" :y="node.y + 39" text-anchor="middle" :fill="node.code === rootCode ? '#e7f2ff' : '#8191a5'" font-size="11">{{ short(node.code, 22) }}</text>
      </g>
    </svg>
  </div>
</template>
<script>
  export default {
    props: {
      graph: { type: Object, required: true },
      rootCode: { type: String, default: '' }
    },
    data () { return { scale: 1 } },
    watch: { graph () { this.scale = 1 } },
    computed: {
      markerId () { return `knowledge-arrow-${this.$.uid}` },
      positioned () {
        const nodes = this.graph.nodes || []
        const edges = this.graph.edges || []
        const distance = { [this.rootCode]: 0 }
        if (this.rootCode) {
          const queue = [this.rootCode]
          for (let index = 0; index < queue.length; index++) {
            const current = queue[index]
            edges.forEach(edge => {
              const next = edge.from === current ? edge.to : (edge.to === current ? edge.from : null)
              if (next && distance[next] === undefined) {
                distance[next] = distance[current] + 1
                queue.push(next)
              }
            })
          }
        }
        const ordered = nodes.slice().sort((a, b) => {
          const aDistance = distance[a.code] === undefined ? 999 : distance[a.code]
          const bDistance = distance[b.code] === undefined ? 999 : distance[b.code]
          return aDistance - bDistance || a.code.localeCompare(b.code)
        })
        const columns = this.rootCode ? 4 : 5
        return ordered.map((node, index) => ({ ...node, x: 30 + (index % columns) * 210, y: 32 + Math.floor(index / columns) * 112 }))
      },
      width () { return Math.max(880, Math.min(this.rootCode ? 4 : 5, this.positioned.length) * 210 + 30) },
      height () { return Math.max(260, Math.ceil(this.positioned.length / (this.rootCode ? 4 : 5)) * 112 + 32) },
      lines () {
        const positions = Object.fromEntries(this.positioned.map(node => [node.code, node]))
        return (this.graph.edges || []).filter(edge => positions[edge.from] && positions[edge.to]).map(edge => {
          const from = positions[edge.from]
          const to = positions[edge.to]
          const forward = to.x >= from.x
          return { ...edge, x1: from.x + (forward ? 156 : 0), y1: from.y + 26, x2: to.x + (forward ? -10 : 166), y2: to.y + 26 }
        })
      }
    },
    methods: {
      short (value, limit = 12) { return value.length > limit ? value.slice(0, limit - 1) + '…' : value },
      open (code) { this.$router.push({ name: 'knowledge-detail', params: { code } }) },
      fit () { if (this.$refs.shell) { this.scale = Math.min(1, (this.$refs.shell.clientWidth - 10) / this.width); this.$refs.shell.scrollTo({ left: 0, top: 0, behavior: 'smooth' }) } }
    }
  }
</script>
<style scoped>
  .graph-shell { min-height: 260px; max-height: 490px; overflow: auto; background: #fff; }
  .graph-svg { display: block; }
  .graph-node { cursor: pointer; outline: none; }
  .graph-node:focus rect, .graph-node:hover rect { stroke: #2d8cf0; stroke-width: 2.5; }
  .graph-empty { min-height: 260px; display: grid; place-items: center; color: #8995a5; }
</style>
