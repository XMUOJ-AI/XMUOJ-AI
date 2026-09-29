<template>
  <main class="knowledge-page">
    <header class="page-heading"><div><p class="eyebrow">KNOWLEDGE EXPLORER</p><h1>知识点探索</h1><p>从列表选择知识点，查看它与上下游知识的联系。</p></div></header>
    <div class="explore-layout">
      <aside class="summary card">
        <template v-if="selected">
          <div class="summary-heading"><div><span class="eyebrow">当前知识点</span><h2>{{ selected.name }}</h2><code>{{ selected.code }}</code></div><router-link :to="{ name: 'knowledge-detail', params: { code: selected.code } }">查看详情</router-link></div>
          <dl><div><dt>分类</dt><dd>{{ categoryLabel(selected.category) }}</dd></div><div><dt>层级</dt><dd>L{{ selected.level }}</dd></div><template v-if="graph"><div><dt>前置</dt><dd>{{ graph.edges.filter(edge => edge.to === selected.code).length }}</dd></div><div><dt>后继</dt><dd>{{ graph.edges.filter(edge => edge.from === selected.code).length }}</dd></div></template></dl>
          <p class="summary-description">{{ selected.description || '暂无简介' }}</p>
          <div v-if="selected.aliases && selected.aliases.length" class="aliases"><span>别名</span><Tag v-for="alias in selected.aliases" :key="alias">{{ alias }}</Tag></div>
          <router-link class="detail-button" :to="{ name: 'knowledge-detail', params: { code: selected.code } }">查看完整详情 →</router-link>
        </template>
        <div v-else class="summary-empty"><span class="empty-icon">◎</span><h2>等待选择</h2><p>选择知识点后查看简介</p></div>
      </aside>
      <div class="main-column">
        <section class="graph-section card" aria-label="局部知识图谱">
          <div class="section-heading"><div><span class="eyebrow">LOCAL GRAPH</span><h2>局部知识图谱</h2></div><div class="graph-actions"><button class="mobile-toggle" type="button" :aria-expanded="!graphCollapsed" @click="graphCollapsed = !graphCollapsed">{{ graphCollapsed ? '展开图谱' : '收起图谱' }}</button><router-link :to="{ name: 'knowledge-graph', query: selected ? { root_code: selected.code, depth } : {} }">打开完整图谱 →</router-link></div></div>
          <div v-if="!graphCollapsed" class="graph-content">
          <div class="graph-tools"><span>当前知识点：<strong>{{ selected ? selected.name : '尚未选择' }}</strong></span><label>上下游范围 <select v-model.number="depth" :disabled="!selected" @change="loadGraph"><option v-for="value in 8" :key="value" :value="value">{{ value }} 层</option></select></label><Button size="small" :disabled="!graph" @click="$refs.graph && $refs.graph.fit()">适应画布</Button></div>
          <div v-if="!selected" class="graph-prompt">从下方知识点列表选择一个知识点</div>
          <div v-else-if="graphLoading" class="graph-prompt" role="status">正在加载图谱…</div>
          <div v-else-if="graphError" class="graph-prompt error" role="alert">{{ graphError }} <Button size="small" @click="loadGraph">重试</Button></div>
          <template v-else-if="graph"><Alert v-if="graph.truncated" type="warning">图谱结果已截断，请缩小范围。</Alert><KnowledgeGraph ref="graph" :graph="graph" :root-code="selected.code" /><div class="legend"><span><i class="solid"></i> 必需依赖</span><span><i class="dashed"></i> 推荐依赖</span></div></template></div>
        </section>
        <section class="list-section card" aria-label="知识点列表">
          <div class="section-heading"><div><span class="eyebrow">BROWSE TOPICS</span><h2>知识点列表</h2></div><span class="result-count">共 {{ total }} 个知识点</span></div>
          <p class="helper">点击列表中的知识点，同步更新上方图谱和右侧简介。</p>
          <div class="filters"><form @submit.prevent="applyFilters"><input v-model="draftKeyword" maxlength="128" aria-label="搜索名称、编码或别名" placeholder="搜索名称、编码或别名"><button type="submit">搜索</button></form><select :value="filters.category" aria-label="分类" @change="changeFilter('category', $event.target.value)"><option value="">全部分类</option><option v-for="item in categories" :key="item[0]" :value="item[0]">{{ item[1] }}</option></select><select :value="filters.level" aria-label="层级" @change="changeFilter('level', $event.target.value)"><option value="">全部层级</option><option v-for="value in 5" :key="value" :value="value">L{{ value }}</option></select><Button type="text" @click="resetFilters">重置</Button></div>
          <div v-if="listLoading" class="list-state" role="status">正在加载知识点…</div>
          <div v-else-if="listError" class="list-state error" role="alert">{{ listError }} <Button size="small" @click="loadList">重试</Button></div>
          <div v-else-if="!items.length" class="list-state">没有符合筛选条件的知识点。</div>
          <template v-else><div class="table-wrap"><table><thead><tr><th>编码</th><th>名称</th><th>分类</th><th>层级</th><th>描述</th><th>别名</th></tr></thead><tbody><tr v-for="item in items" :key="item.code" :class="{ selected: selected && selected.code === item.code }" :aria-selected="selected && selected.code === item.code" tabindex="0" @click="select(item)" @keydown.enter="select(item)" @keydown.space.prevent="select(item)"><td><code>{{ item.code }}</code></td><td><strong>{{ item.name }}</strong></td><td>{{ categoryLabel(item.category) }}</td><td>L{{ item.level }}</td><td class="description-cell">{{ item.description || '—' }}</td><td>{{ item.aliases.join('、') || '—' }}</td></tr></tbody></table></div><div class="pagination"><span>第 {{ filters.page }} 页</span><Button size="small" :disabled="filters.page <= 1" @click="changeFilter('page', filters.page - 1)">上一页</Button><Button size="small" :disabled="filters.page * filters.page_size >= total" @click="changeFilter('page', filters.page + 1)">下一页</Button><label>每页 <select :value="filters.page_size" @change="changeFilter('page_size', Number($event.target.value))"><option :value="10">10</option><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option></select> 条</label></div></template>
        </section>
      </div>
    </div>
  </main>
</template>
<script>
  import { mapGetters } from 'vuex'
  import { listKnowledge, getKnowledgeGraph } from './knowledgeApi'
  import { categories, categoryLabel, positiveInt, errorMessage } from './knowledgeData'
  import KnowledgeGraph from './KnowledgeGraph.vue'

  export default {
    components: { KnowledgeGraph },
    data () { return { categories, selected: null, items: [], total: 0, graph: null, depth: 3, draftKeyword: '', graphCollapsed: false, listLoading: false, graphLoading: false, listError: '', graphError: '', listRequest: 0, graphRequest: 0, alive: true } },
    computed: {
      ...mapGetters(['isAuthenticated']),
      filters () { const q = this.$route.query; return { keyword: String(q.keyword || ''), category: categories.some(item => item[0] === q.category) ? q.category : '', level: positiveInt(q.level, '', 5), page: positiveInt(q.page, 1, 1000000), page_size: positiveInt(q.page_size, 20, 100) } },
      filterKey () { return JSON.stringify(this.filters) }
    },
    mounted () { this.draftKeyword = this.filters.keyword; this.loadList() },
    beforeUnmount () { this.alive = false; this.listRequest++; this.graphRequest++ },
    watch: {
      filterKey () { this.draftKeyword = this.filters.keyword; this.loadList() },
      isAuthenticated (value) { if (!value) this.clearAll() }
    },
    methods: {
      categoryLabel,
      clearAll () { this.listRequest++; this.graphRequest++; this.items = []; this.total = 0; this.selected = null; this.graph = null; this.listLoading = false; this.graphLoading = false },
      async loadList () {
        const request = ++this.listRequest
        this.listLoading = true; this.listError = ''; this.items = []
        try {
          const params = Object.fromEntries(Object.entries(this.filters).filter(([, value]) => value !== '' && value !== null))
          const data = await listKnowledge(params)
          if (!this.alive || request !== this.listRequest) return
          this.items = data.items; this.total = data.total
        } catch (error) {
          if (!this.alive || request !== this.listRequest) return
          this.listError = errorMessage(error); this.total = 0
        } finally { if (this.alive && request === this.listRequest) this.listLoading = false }
      },
      select (item) { this.selected = item; this.graph = null; this.loadGraph() },
      async loadGraph () {
        if (!this.selected) return
        const request = ++this.graphRequest
        const code = this.selected.code
        this.graphLoading = true; this.graphError = ''
        try {
          const data = await getKnowledgeGraph({ root_code: code, depth: this.depth })
          if (this.alive && request === this.graphRequest) this.graph = data
        } catch (error) {
          if (this.alive && request === this.graphRequest) { this.graph = null; this.graphError = errorMessage(error) }
        } finally { if (this.alive && request === this.graphRequest) this.graphLoading = false }
      },
      applyFilters () { this.changeFilter('keyword', this.draftKeyword.trim()) },
      changeFilter (key, value) {
        const next = { ...this.filters, [key]: value }
        if (key !== 'page') next.page = 1
        this.$router.push({ name: 'knowledge', query: Object.fromEntries(Object.entries(next).filter(([, item]) => item !== '' && item !== null)) })
      },
      resetFilters () { this.draftKeyword = ''; this.$router.push({ name: 'knowledge' }) }
    }
  }
</script>
<style scoped>
  .knowledge-page { max-width: 1600px; margin: 0 auto; color: #26364a; }
  .page-heading { margin: 4px 0 22px; }.page-heading h1 { font-size: 26px; margin: 4px 0; }.page-heading p:last-child { color: #738196; }
  .eyebrow { color: #2d8cf0; font-size: 11px; font-weight: 700; letter-spacing: .12em; }
  .explore-layout { display: grid; grid-template-columns: minmax(0, 1fr) 290px; gap: 22px; align-items: start; }
  .main-column { grid-column: 1; grid-row: 1; min-width: 0; display: grid; gap: 22px; }.summary { grid-column: 2; grid-row: 1; position: sticky; top: 92px; }
  .card { background: #fff; border: 1px solid #e4eaf2; border-radius: 10px; box-shadow: 0 5px 22px rgba(30, 57, 91, .05); padding: 22px; }
  .section-heading, .summary-heading { display: flex; justify-content: space-between; align-items: start; gap: 15px; }.section-heading h2, .summary h2 { font-size: 19px; margin: 4px 0 0; }.section-heading a, .summary-heading a { color: #2d8cf0; white-space: nowrap; }.result-count { color: #8290a3; font-size: 13px; }
  .graph-actions { display: flex; gap: 12px; align-items: center; }.mobile-toggle { display: none; background: none; border: 0; color: #2d8cf0; cursor: pointer; }
  .graph-tools { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin: 20px 0 12px; color: #66778c; }.graph-tools strong { color: #27394e; }.graph-tools select, .filters select, .pagination select { margin-left: 5px; border: 1px solid #dce4ef; border-radius: 5px; padding: 6px 8px; background: white; color: #26364a; }.graph-prompt { height: 260px; display: flex; align-items: center; justify-content: center; gap: 10px; color: #8492a5; background: #f9fbfe; border: 1px dashed #dce6f2; border-radius: 7px; }
  .legend { display: flex; justify-content: end; gap: 20px; color: #748398; font-size: 12px; margin-top: 10px; }.legend i { display: inline-block; width: 28px; vertical-align: middle; border-top: 2px solid #8291a6; }.legend .dashed { border-top-style: dashed; }
  .helper { color: #8391a5; margin: 12px 0 18px; }.filters { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 16px; }.filters form { display: flex; flex: 1; min-width: 230px; }.filters input { flex: 1; min-width: 0; border: 1px solid #dce4ef; border-radius: 5px 0 0 5px; padding: 9px 11px; }.filters form button { color: white; background: #2d8cf0; border: 0; padding: 0 17px; border-radius: 0 5px 5px 0; cursor: pointer; }.filters select { margin: 0; min-width: 120px; padding: 9px; }
  .table-wrap { overflow-x: auto; }table { width: 100%; border-collapse: collapse; min-width: 760px; }th { background: #f6f9fd; color: #66778c; font-weight: 600; text-align: left; }th, td { padding: 12px 10px; border-bottom: 1px solid #edf1f6; }tbody tr { cursor: pointer; }tbody tr:hover, tbody tr:focus { background: #f2f8ff; outline: none; }tbody tr.selected { background: #eaf3ff; box-shadow: inset 3px 0 #2d8cf0; }td strong { color: #2d8cf0; }td code, .summary code { color: #66778c; font-family: Consolas, monospace; }.description-cell { max-width: 260px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }.list-state { padding: 65px 10px; text-align: center; color: #8290a3; }.error { color: #b94b4b; }.pagination { display: flex; align-items: center; justify-content: end; gap: 9px; padding-top: 18px; color: #728197; }
  .summary { min-height: 360px; }.summary-heading { flex-wrap: wrap; }.summary dl { margin-top: 25px; }.summary dl div { display: flex; gap: 18px; margin: 15px 0; }.summary dt { color: #8290a3; min-width: 38px; }.summary dd { margin: 0; }.summary-description { line-height: 1.7; border-top: 1px solid #edf1f6; padding-top: 16px; white-space: pre-wrap; }.aliases { margin-top: 16px; color: #8290a3; }.detail-button { display: block; text-align: center; color: white; background: #2d8cf0; padding: 10px; border-radius: 5px; margin-top: 24px; }.detail-button:hover { color: white; background: #1675d1; }.summary-empty { text-align: center; padding: 82px 0; color: #8290a3; }.summary-empty h2 { color: #52637a; }.empty-icon { color: #2d8cf0; font-size: 40px; }
  @media (max-width: 900px) { .explore-layout { display: flex; flex-direction: column; }.summary, .main-column { width: 100%; }.summary { position: static; min-height: 0; order: -1; }.summary-empty { padding: 20px 0; }.mobile-toggle { display: inline; } }
  @media (max-width: 600px) { .card { padding: 16px; }.section-heading { flex-wrap: wrap; }.pagination { justify-content: start; flex-wrap: wrap; } }
</style>
