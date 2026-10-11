<template>
  <main class="map-page">
    <div class="heading"><div><router-link :to="{ name: 'knowledge' }">← 知识点探索</router-link><h1>完整知识图谱</h1><p>探索知识之间的必需依赖和推荐依赖。</p></div></div>
    <section class="card"><div class="filters"><form @submit.prevent="applyRoot"><input v-model="rootDraft" aria-label="节点编码" placeholder="输入知识点编码定位节点"><button type="submit">定位节点</button></form><label>分类 <select :value="filters.category" @change="changeFilter('category', $event.target.value)"><option value="">全部分类</option><option v-for="item in categories" :key="item[0]" :value="item[0]">{{ item[1] }}</option></select></label><label>层级 <select :value="filters.level" @change="changeFilter('level', $event.target.value)"><option value="">全部层级</option><option v-for="value in 5" :key="value" :value="value">L{{ value }}</option></select></label><label>深度 <select :value="filters.depth" :disabled="!filters.root_code" @change="changeFilter('depth', Number($event.target.value))"><option v-for="value in 8" :key="value" :value="value">{{ value }} 层</option></select></label><Button type="text" @click="reset">重置</Button></div><p v-if="!filters.root_code" class="hint">未设置根节点时显示全部知识点，深度筛选暂不生效。</p>
      <div class="toolbar"><div><Button :type="view === 'graph' ? 'primary' : 'default'" @click="view = 'graph'">图形视图</Button><Button :type="view === 'table' ? 'primary' : 'default'" @click="view = 'table'">关系表格</Button></div><div v-if="view === 'graph' && graph" class="zoom-controls"><Button size="small" @click="$refs.graph && $refs.graph.fit()">适应画布</Button><Button size="small" aria-label="缩小图谱" title="缩小图谱" @click="$refs.graph && $refs.graph.zoom(-0.25)">−</Button><Button size="small" aria-label="放大图谱" title="放大图谱" @click="$refs.graph && $refs.graph.zoom(0.25)">+</Button></div></div>
      <div v-if="loading" class="state" role="status">正在加载完整图谱…</div><div v-else-if="error" class="state error" role="alert">{{ error }} <Button size="small" @click="load">重试</Button></div><template v-else-if="graph"><Alert v-if="graph.truncated" type="warning" show-icon>图谱结果超过显示上限，请设置根节点或缩小筛选范围。</Alert><KnowledgeGraph v-if="view === 'graph'" ref="graph" :graph="graph" :root-code="filters.root_code" @select-node="changeFilter('root_code', $event)" /><div v-else class="tables"><h2>知识点（{{ graph.nodes.length }}）</h2><table><thead><tr><th>编码</th><th>名称</th><th>层级</th><th>操作</th></tr></thead><tbody><tr v-for="node in graph.nodes" :key="node.code"><td><code>{{ node.code }}</code></td><td>{{ node.name }}</td><td>L{{ node.level }}</td><td><router-link :to="{ name: 'knowledge-detail', params: { code: node.code } }">查看详情</router-link></td></tr></tbody></table><h2>依赖关系（{{ graph.edges.length }}）</h2><p v-if="!graph.edges.length" class="hint">当前范围内没有依赖关系。</p><table v-else><thead><tr><th>前置知识点</th><th>后继知识点</th><th>类型</th><th>权重</th></tr></thead><tbody><tr v-for="(edge, index) in graph.edges" :key="index"><td><router-link :to="{ name: 'knowledge-detail', params: { code: edge.from } }">{{ nameOf(edge.from) }}</router-link></td><td><router-link :to="{ name: 'knowledge-detail', params: { code: edge.to } }">{{ nameOf(edge.to) }}</router-link></td><td>{{ edge.relation_type === 'required' ? '必需依赖' : '推荐依赖' }}</td><td>{{ edge.weight }}</td></tr></tbody></table></div><div class="legend"><span>━━━━ 必需依赖</span><span>┄┄┄ 推荐依赖</span></div></template>
    </section>
  </main>
</template>
<script>
  import { mapGetters } from 'vuex'
  import { getKnowledgeGraph } from './knowledgeApi'
  import { categories, positiveInt, errorMessage } from './knowledgeData'
  import KnowledgeGraph from './KnowledgeGraph.vue'
  export default {
    components: { KnowledgeGraph },
    data () { return { categories, rootDraft: '', graph: null, view: 'graph', loading: false, error: '', request: 0, alive: true } },
    computed: {
      ...mapGetters(['isAuthenticated']),
      filters () { const q = this.$route.query; return { root_code: String(q.root_code || ''), category: categories.some(item => item[0] === q.category) ? q.category : '', level: positiveInt(q.level, '', 5), depth: positiveInt(q.depth, 3, 8) } },
      filterKey () { return JSON.stringify(this.filters) }
    },
    mounted () { this.rootDraft = this.filters.root_code; this.load() },
    beforeUnmount () { this.alive = false; this.request++ },
    watch: {
      filterKey () { this.rootDraft = this.filters.root_code; this.load() },
      isAuthenticated (value) { if (!value) { this.request++; this.graph = null; this.loading = false } }
    },
    methods: {
      async load () {
        const request = ++this.request
        const params = { ...this.filters }
        if (!params.root_code) { delete params.root_code; delete params.depth }
        if (!params.category) delete params.category
        if (!params.level) delete params.level
        this.graph = null; this.error = ''; this.loading = true
        try { const data = await getKnowledgeGraph(params); if (this.alive && request === this.request) this.graph = data } catch (error) { if (this.alive && request === this.request) this.error = errorMessage(error) } finally { if (this.alive && request === this.request) this.loading = false }
      },
      applyRoot () { const value = this.rootDraft.trim(); if (!value || /^[a-z][a-z0-9_]{0,63}$/.test(value)) this.changeFilter('root_code', value); else this.error = '请输入合法的知识点编码。' },
      changeFilter (key, value) { const next = { ...this.filters, [key]: value }; this.$router.push({ name: 'knowledge-graph', query: Object.fromEntries(Object.entries(next).filter(([, item]) => item !== '' && item !== null)) }) },
      reset () { this.rootDraft = ''; this.$router.push({ name: 'knowledge-graph' }) },
      nameOf (code) { const node = (this.graph.nodes || []).find(item => item.code === code); return node ? `${node.name} (${code})` : code }
    }
  }
</script>
<style scoped>
  .map-page { max-width: 1500px; margin: 0 auto; color: #26364a; }.heading { margin-bottom: 22px; }.heading h1 { margin: 10px 0 4px; font-size: 26px; }.heading p, .hint { color: #8391a5; }.card { background: white; padding: 22px; border: 1px solid #e4eaf2; border-radius: 10px; box-shadow: 0 5px 22px rgba(30,57,91,.05); }.filters { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }.filters form { display: flex; flex: 1; min-width: 250px; }.filters input { flex: 1; min-width: 0; padding: 9px; border: 1px solid #dce4ef; border-radius: 5px 0 0 5px; }.filters button { background: #2d8cf0; color: white; border: 0; border-radius: 0 5px 5px 0; padding: 0 16px; cursor: pointer; }.filters select { border: 1px solid #dce4ef; padding: 9px; border-radius: 5px; background: white; color: #26364a; }.toolbar { display: flex; justify-content: space-between; margin: 22px 0 14px; }.toolbar .ivu-btn + .ivu-btn { margin-left: 8px; }.toolbar .zoom-controls { display: inline-flex; align-items: center; }.state { min-height: 280px; display: grid; place-items: center; color: #8290a3; }.error { color: #b94b4b; }.tables { overflow-x: auto; }.tables h2 { font-size: 17px; margin: 25px 0 12px; }.tables table { width: 100%; border-collapse: collapse; min-width: 600px; }.tables th { background: #f6f9fd; }.tables td, .tables th { text-align: left; padding: 11px; border-bottom: 1px solid #edf1f6; }.legend { display: flex; justify-content: end; gap: 18px; color: #77869a; font-size: 12px; margin-top: 14px; }
</style>
